from __future__ import annotations
import asyncio
import json
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
import pytest
from domain.llm.agent.tools.rag_search import RAGSearchTool
from domain.rag.document_watcher import DocumentWatcher
from domain.rag.rag_manager import RAGManager
from domain.rag.vector_store import RAGQueryResult, VectorStore
from shared.event_types import EVENT_RAG_INDEX_COMPLETE, EVENT_RAG_INDEX_ERROR
from shared.file_change import FileChange

class _NoopWorker:

    def __init__(self):
        self.is_running = True
        self.stopped = False

    def start_and_wait(self, timeout=5.0):
        del timeout
        self.is_running = True
        return True

    def cancel_pending(self):
        return None

    def submit(self, fn, *args, **kwargs):
        future = Future()
        future.set_result(None)
        return future

    def stop(self):
        self.stopped = True
        self.is_running = False

class _RecordingEventBus:

    def __init__(self):
        self.events = []

    def publish(self, event_type, data):
        self.events.append((event_type, data))

class _FakeEmbedder:
    provider_id = 'fake'
    model_name = 'embedding-test'

    def __init__(self, dimensions: int=3):
        self.dimensions = dimensions

    def embed_texts(self, texts):
        return [[float(index + 1)] * self.dimensions for index, _ in enumerate(texts)]

    def embed_single(self, text):
        del text
        return [1.0] * self.dimensions

class _FakeVectorStore:
    backend_name = 'fake-store'
    metric = 'cosine'

    def __init__(self, project_root: str, storage_subdir: str, *, fail_upsert=False):
        del storage_subdir
        self.project_root = str(project_root)
        self.collection_name = f'collection-{Path(project_root).name}'
        self.is_initialized = False
        self.fail_upsert = fail_upsert
        self.clear_calls = 0
        self.upsert_calls = []
        self.deleted = []
        self.deleted_prefixes = []
        self.count_calls = 0

    def initialize(self):
        self.is_initialized = True

    def clear(self):
        if not self.is_initialized:
            raise RuntimeError('not initialized')
        self.clear_calls += 1

    def upsert_file(self, rel_path, chunks, vectors):
        if self.fail_upsert:
            raise RuntimeError('simulated upsert failure')
        self.upsert_calls.append((rel_path, len(chunks), len(vectors)))

    def delete_file(self, rel_path):
        self.deleted.append(rel_path)

    def delete_prefix(self, rel_path):
        self.deleted_prefixes.append(rel_path)
        return 1

    def query(self, vector, top_k=10):
        del vector, top_k
        return []

    def count(self):
        self.count_calls += 1
        return sum((call[1] for call in self.upsert_calls))

def _build_manager(tmp_path: Path, *, dimensions=3, fail_upsert=False):
    stores = []

    def store_factory(project_root, storage_subdir):
        store = _FakeVectorStore(project_root, storage_subdir, fail_upsert=fail_upsert)
        stores.append(store)
        return store
    manager = RAGManager(embedder_factory=lambda: _FakeEmbedder(dimensions), vector_store_factory=store_factory, worker=_NoopWorker())
    runtime = manager._create_runtime(str(tmp_path))
    runtime.vector_store.initialize()
    runtime.state.index_meta = manager._new_index_meta(runtime)
    return (manager, runtime, stores)

def test_stale_project_runtime_cannot_commit_to_new_project(tmp_path):
    project_a = tmp_path / 'a'
    project_b = tmp_path / 'b'
    project_a.mkdir()
    project_b.mkdir()
    source_a = project_a / 'notes.txt'
    source_a.write_text('project a', encoding='utf-8')
    manager, runtime_a, stores = _build_manager(project_a)
    runtime_b = manager._create_runtime(str(project_b))
    runtime_b.vector_store.initialize()
    runtime_b.state.index_meta = manager._new_index_meta(runtime_b)
    with pytest.raises(RuntimeError, match='Stale RAG runtime'):
        manager.index_single_file(str(source_a), runtime_a)
    assert stores[0].upsert_calls == []
    assert stores[1].upsert_calls == []

def test_workspace_sync_rescans_only_the_current_rag_runtime(tmp_path):
    project = tmp_path / 'current'
    other_project = tmp_path / 'other'
    project.mkdir()
    other_project.mkdir()
    manager, runtime, _ = _build_manager(project)
    calls = []
    manager.trigger_index = lambda: calls.append((manager.project_root, manager.generation))
    manager._on_workspace_sync_required({'data': {'project_root': str(other_project), 'reason': 'rollback'}})
    manager._on_workspace_sync_required({'data': {'project_root': str(project), 'reason': 'rollback'}})
    assert calls == [(runtime.project_root, runtime.generation)]
    runtime.cancelled.set()
    manager._on_workspace_sync_required({'data': {'project_root': str(project), 'reason': 'rollback'}})
    assert calls == [(runtime.project_root, runtime.generation)]

def test_signature_dimension_change_clears_collection_and_meta(tmp_path):
    manager, runtime, stores = _build_manager(tmp_path, dimensions=1024)
    old_signature = runtime.signature.to_dict()
    old_signature['dimensions'] = 2048
    runtime.state.index_meta = {'version': 1, 'signature': old_signature, 'files': {'old.txt': {'status': 'processed', 'chunks_count': 1}}, 'stats': {}}
    manager._ensure_index_signature(runtime)
    assert stores[0].clear_calls == 1
    assert runtime.state.index_meta['signature']['dimensions'] == 1024
    assert runtime.state.index_meta['files'] == {}
    saved = json.loads((tmp_path / '.circuit_ai' / 'rag_storage' / 'index_meta.json').read_text(encoding='utf-8'))
    assert saved['signature']['dimensions'] == 1024

def test_missing_meta_is_untrusted_even_when_signature_was_synthesized(tmp_path):
    manager, runtime, stores = _build_manager(tmp_path)
    runtime.state.meta_loaded_from_disk = False
    manager._ensure_index_signature(runtime)
    assert stores[0].clear_calls == 1

def test_meta_vector_count_mismatch_forces_rebuild(tmp_path):
    manager, runtime, stores = _build_manager(tmp_path)
    runtime.state.meta_loaded_from_disk = True
    runtime.state.index_meta['files'] = {'missing-vectors.txt': {'status': 'processed', 'chunks_count': 2}}
    manager._ensure_index_signature(runtime)
    assert stores[0].clear_calls == 1
    assert runtime.state.index_meta['files'] == {}

def test_upsert_failure_is_recorded_as_failed_not_processed(tmp_path):
    source = tmp_path / 'notes.txt'
    source.write_text('content for vector indexing', encoding='utf-8')
    manager, runtime, _ = _build_manager(tmp_path, fail_upsert=True)
    manager.index_single_file(str(source), runtime)
    meta = runtime.state.index_meta['files']['notes.txt']
    assert meta['status'] == 'failed'
    assert 'simulated upsert failure' in meta['error']
    assert meta['stale'] is False

def test_empty_file_deletes_old_vectors_and_commits_zero_chunks(tmp_path):
    source = tmp_path / 'empty.txt'
    source.write_text('   \n', encoding='utf-8')
    manager, runtime, stores = _build_manager(tmp_path)
    runtime.state.index_meta['files'] = {'empty.txt': {'status': 'processed', 'chunks_count': 2}}
    manager.index_single_file(str(source), runtime)
    assert stores[0].deleted == ['empty.txt']
    meta = runtime.state.index_meta['files']['empty.txt']
    assert meta['status'] == 'processed'
    assert meta['chunks_count'] == 0
    assert meta['empty'] is True

def test_extraction_failure_keeps_last_good_marked_stale(tmp_path, monkeypatch):
    source = tmp_path / 'broken.pdf'
    source.write_bytes(b'not-an-empty-document')
    manager, runtime, stores = _build_manager(tmp_path)
    runtime.state.index_meta['files'] = {'broken.pdf': {'status': 'processed', 'chunks_count': 4}}
    monkeypatch.setattr('domain.rag.rag_manager.extract_indexable_content', lambda path: '')
    manager.index_single_file(str(source), runtime)
    assert stores[0].deleted == []
    meta = runtime.state.index_meta['files']['broken.pdf']
    assert meta['status'] == 'failed'
    assert meta['stale'] is True
    assert meta['chunks_count'] == 4

def test_delete_removes_vectors_before_meta(tmp_path):
    manager, runtime, stores = _build_manager(tmp_path)
    runtime.state.index_meta['files'] = {'gone.txt': {'status': 'processed', 'chunks_count': 1}}
    manager._delete_file_runtime(runtime, 'gone.txt')
    assert stores[0].deleted == ['gone.txt']
    assert 'gone.txt' not in runtime.state.index_meta['files']

def test_directory_delete_removes_entire_meta_prefix(tmp_path):
    manager, runtime, stores = _build_manager(tmp_path)
    runtime.state.index_meta['files'] = {'docs/a.txt': {'status': 'processed', 'chunks_count': 1}, 'docs/nested/b.txt': {'status': 'processed', 'chunks_count': 1}, 'other.txt': {'status': 'processed', 'chunks_count': 1}}
    manager._delete_file_runtime(runtime, 'docs', is_directory=True)
    assert stores[0].deleted_prefixes == ['docs']
    assert set(runtime.state.index_meta['files']) == {'other.txt'}

def test_vector_store_write_failure_propagates(tmp_path):

    class BrokenCollection:

        def __init__(self):
            self.deleted = []

        def get(self, **kwargs):
            del kwargs
            return {'ids': ['old']}

        def upsert(self, **kwargs):
            del kwargs
            raise ValueError('bad dimension')

        def delete(self, ids):
            self.deleted.extend(ids)

    class Chunk:
        chunk_id = 'one'
        content = 'content'
        file_path = 'one.txt'
        chunk_index = 0
        file_type = '.txt'
        symbol_name = ''
    store = VectorStore(str(tmp_path))
    collection = BrokenCollection()
    store._collection = collection
    with pytest.raises(RuntimeError, match='bad dimension'):
        store.upsert_file('one.txt', [Chunk()], [[1.0, 2.0]])
    assert collection.deleted == []

def test_document_watcher_routes_delete_and_move_with_current_generation(tmp_path):

    class FileManager:
        project_generation = 7

    class Manager:
        is_available = True
        project_root = str(tmp_path)
        generation = 7

        def __init__(self):
            self.calls = []

        def trigger_delete_file(self, path, is_directory=False):
            self.calls.append(('delete', path, is_directory))

        def trigger_move_file(self, old, new, is_directory=False):
            self.calls.append(('move', old, new, is_directory))

        def trigger_index_single_file(self, path):
            self.calls.append(('index', path))
    manager = Manager()
    watcher = DocumentWatcher(rag_manager=manager, file_manager=FileManager())
    old_path = str(tmp_path / 'old.txt')
    new_path = str(tmp_path / 'new.txt')
    watcher._on_file_modified(FileChange(operation='delete', path=old_path, dest_path='', is_directory=False, origin='test', project_root=str(tmp_path), generation=7, revision='missing'))
    watcher._on_file_modified(FileChange(operation='move', path=old_path, dest_path=new_path, is_directory=False, origin='test', project_root=str(tmp_path), generation=7, revision='test-revision'))
    assert manager.calls == [('delete', old_path, False), ('move', old_path, new_path, False)]

def test_document_watcher_rejects_stale_generation_and_routes_directories(tmp_path):

    class FileManager:
        project_generation = 4

    class Manager:
        is_available = True
        project_root = str(tmp_path)
        generation = 4

        def __init__(self):
            self.calls = []

        def trigger_delete_file(self, path, is_directory=False):
            self.calls.append(('delete', path, is_directory))
    manager = Manager()
    watcher = DocumentWatcher(rag_manager=manager, file_manager=FileManager())
    directory = str(tmp_path / 'docs')
    watcher._on_file_modified(FileChange(operation='delete', path=directory, dest_path='', project_root=str(tmp_path), generation=3, is_directory=True, origin='test', revision='missing'))
    watcher._on_file_modified(FileChange(operation='delete', path=directory, dest_path='', project_root=str(tmp_path), generation=4, is_directory=True, origin='test', revision='missing'))
    assert manager.calls == [('delete', directory, True)]

def test_file_generation_remains_valid_after_rag_config_refresh(tmp_path):

    class FileManager:
        project_generation = 4

    class Manager:
        is_available = True
        project_root = str(tmp_path)
        generation = 9

        def __init__(self):
            self.calls = []

        def trigger_index_single_file(self, path):
            self.calls.append(path)
    manager = Manager()
    watcher = DocumentWatcher(rag_manager=manager, file_manager=FileManager())
    path = str(tmp_path / 'still-current.txt')
    watcher._on_file_modified(FileChange(operation='update', path=path, dest_path='', is_directory=False, origin='test', project_root=str(tmp_path), generation=4, revision='test-revision'))
    assert manager.calls == [path]

def test_manager_query_failures_raise_instead_of_returning_empty_results(tmp_path, monkeypatch):
    unavailable = RAGManager(worker=_NoopWorker())
    with pytest.raises(RuntimeError, match='index library is unavailable'):
        unavailable.query('power rail')
    manager, _, _ = _build_manager(tmp_path)
    monkeypatch.setattr(manager._worker, 'submit', lambda *args, **kwargs: None)

    async def query_with_stopped_worker():
        with pytest.raises(RuntimeError, match='worker is not running'):
            await manager.query_async('power rail')
    asyncio.run(query_with_stopped_worker())

def test_successful_empty_query_remains_a_non_error_tool_result():

    class EmptyQueryManager:
        is_available = True

        async def query_async(self, query):
            del query
            return RAGQueryResult()
    result = asyncio.run(RAGSearchTool().execute('call-rag', {'query': 'unknown component'}, SimpleNamespace(rag_query_service=EmptyQueryManager())))
    assert result.is_error is False
    assert result.details == {'query': 'unknown component', 'results_count': 0}

def test_manager_rejects_clear_token_from_old_generation(tmp_path):
    project_a = tmp_path / 'a'
    project_b = tmp_path / 'b'
    project_a.mkdir()
    project_b.mkdir()
    manager, runtime_a, stores = _build_manager(project_a)
    runtime_b = manager._create_runtime(str(project_b))
    runtime_b.vector_store.initialize()
    runtime_b.state.index_meta = manager._new_index_meta(runtime_b)

    async def scenario():
        with pytest.raises(RuntimeError, match='generation changed'):
            await manager.clear_index_async(expected_generation=runtime_a.generation, expected_project_root=runtime_a.project_root)
    import asyncio
    asyncio.run(scenario())
    assert stores[0].clear_calls == 0
    assert stores[1].clear_calls == 0

def test_manager_stop_is_idempotent_and_stops_attached_watcher(tmp_path):
    manager, runtime, _ = _build_manager(tmp_path)

    class Watcher:

        def __init__(self):
            self.stop_calls = 0

        def stop(self):
            self.stop_calls += 1
    watcher = Watcher()
    manager.attach_document_watcher(watcher)
    manager.stop()
    manager.stop()
    assert runtime.cancelled.is_set()
    assert watcher.stop_calls == 1
    assert manager._worker.stopped is True
