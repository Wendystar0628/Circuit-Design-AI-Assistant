# Test File Manager
"""
FileManager 单元测试

使用 unittest 框架，可直接运行
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestFileManager(unittest.TestCase):
    """FileManager 测试类"""
    
    def setUp(self):
        """创建临时测试目录和 FileManager 实例"""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        
        from infrastructure.persistence.file_manager import FileManager
        self.fm = FileManager()
        self.fm.set_work_dir(self.temp_path)
    
    def tearDown(self):
        """清理临时目录"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    # ============================================================
    # 基本文件操作测试
    # ============================================================
    
    def test_write_and_read_file(self):
        """测试写入和读取文件"""
        test_file = self.temp_path / "test.txt"
        content = "Hello, World!"
        
        result = self.fm.write_file(test_file, content)
        self.assertTrue(result)
        self.assertTrue(test_file.exists())
        
        read_content = self.fm.read_file(test_file)
        self.assertEqual(read_content, content)
        print("✓ test_write_and_read_file 通过")
    
    def test_write_binary_file(self):
        """测试写入和读取二进制文件"""
        test_file = self.temp_path / "test.bin"
        content = b"\x00\x01\x02\x03\x04"
        
        result = self.fm.write_file(test_file, content)
        self.assertTrue(result)
        
        read_content = self.fm.read_file(test_file, binary=True)
        self.assertEqual(read_content, content)
        print("✓ test_write_binary_file 通过")
    
    def test_delete_file(self):
        """测试删除文件"""
        test_file = self.temp_path / "to_delete.txt"
        test_file.write_text("delete me")
        
        result = self.fm.delete_file(test_file)
        self.assertTrue(result)
        self.assertFalse(test_file.exists())
        print("✓ test_delete_file 通过")
    
    def test_file_exists(self):
        """测试文件存在检查"""
        test_file = self.temp_path / "exists.txt"
        
        self.assertFalse(self.fm.file_exists(test_file))
        
        test_file.write_text("content")
        self.assertTrue(self.fm.file_exists(test_file))
        print("✓ test_file_exists 通过")
    
    # ============================================================
    # create_file 幂等性测试
    # ============================================================
    
    def test_create_file_new(self):
        """测试创建新文件"""
        test_file = self.temp_path / "new_file.txt"
        content = "new content"
        
        result = self.fm.create_file(test_file, content)
        self.assertTrue(result)
        self.assertEqual(test_file.read_text(), content)
        print("✓ test_create_file_new 通过")
    
    def test_create_file_idempotent_same_content(self):
        """测试幂等性：相同内容"""
        test_file = self.temp_path / "idempotent.txt"
        content = "same content"
        
        self.fm.create_file(test_file, content)
        result = self.fm.create_file(test_file, content)
        self.assertTrue(result)
        print("✓ test_create_file_idempotent_same_content 通过")
    
    def test_create_file_different_content_raises(self):
        """测试幂等性：不同内容应抛出异常"""
        from infrastructure.persistence.file_manager import FileExistsError
        
        test_file = self.temp_path / "conflict.txt"
        self.fm.create_file(test_file, "original content")
        
        with self.assertRaises(FileExistsError):
            self.fm.create_file(test_file, "different content")
        print("✓ test_create_file_different_content_raises 通过")
    
    # ============================================================
    # patch_file 测试
    # ============================================================
    
    def test_patch_file_single_match(self):
        """测试 patch_file 单次匹配"""
        test_file = self.temp_path / "patch.txt"
        test_file.write_text("Hello, World!")
        
        count = self.fm.patch_file(test_file, "World", "Python")
        self.assertEqual(count, 1)
        self.assertEqual(test_file.read_text(), "Hello, Python!")
        print("✓ test_patch_file_single_match 通过")
    
    def test_patch_file_replace_all(self):
        """测试 patch_file 替换所有"""
        test_file = self.temp_path / "patch_all.txt"
        test_file.write_text("a b a c a")
        
        count = self.fm.patch_file(test_file, "a", "X", occurrence=0)
        self.assertEqual(count, 3)
        self.assertEqual(test_file.read_text(), "X b X c X")
        print("✓ test_patch_file_replace_all 通过")
    
    def test_patch_file_specific_occurrence(self):
        """测试 patch_file 指定位置"""
        test_file = self.temp_path / "patch_specific.txt"
        test_file.write_text("a b a c a")
        
        count = self.fm.patch_file(test_file, "a", "X", occurrence=2)
        self.assertEqual(count, 1)
        self.assertEqual(test_file.read_text(), "a b X c a")
        print("✓ test_patch_file_specific_occurrence 通过")
    
    def test_patch_file_idempotent(self):
        """测试 patch_file 幂等性"""
        test_file = self.temp_path / "patch_idempotent.txt"
        test_file.write_text("Hello, Python!")
        
        count = self.fm.patch_file(test_file, "World", "Python")
        self.assertEqual(count, 0)
        self.assertEqual(test_file.read_text(), "Hello, Python!")
        print("✓ test_patch_file_idempotent 通过")
    
    def test_patch_file_not_found_raises(self):
        """测试 patch_file 搜索内容不存在"""
        from infrastructure.persistence.file_manager import SearchNotFoundError
        
        test_file = self.temp_path / "patch_notfound.txt"
        test_file.write_text("Hello, World!")
        
        with self.assertRaises(SearchNotFoundError):
            self.fm.patch_file(test_file, "NotExist", "Replace")
        print("✓ test_patch_file_not_found_raises 通过")
    
    def test_patch_file_multiple_match_raises(self):
        """测试 patch_file 多处匹配未指定 occurrence"""
        from infrastructure.persistence.file_manager import MultipleMatchError
        
        test_file = self.temp_path / "patch_multiple.txt"
        test_file.write_text("a b a c a")
        
        with self.assertRaises(MultipleMatchError) as ctx:
            self.fm.patch_file(test_file, "a", "X")
        
        self.assertEqual(ctx.exception.match_count, 3)
        print("✓ test_patch_file_multiple_match_raises 通过")
    
    # ============================================================
    # update_file 测试
    # ============================================================
    
    def test_update_file(self):
        """测试 update_file 整体替换"""
        test_file = self.temp_path / "update.txt"
        test_file.write_text("old content")
        
        result = self.fm.update_file(test_file, "new content")
        self.assertTrue(result)
        self.assertEqual(test_file.read_text(), "new content")
        print("✓ test_update_file 通过")
    
    def test_update_file_idempotent(self):
        """测试 update_file 幂等性"""
        test_file = self.temp_path / "update_idempotent.txt"
        content = "same content"
        test_file.write_text(content)
        
        result = self.fm.update_file(test_file, content)
        self.assertTrue(result)
        print("✓ test_update_file_idempotent 通过")
    
    # ============================================================
    # 目录操作测试
    # ============================================================
    
    def test_ensure_directory(self):
        """测试确保目录存在"""
        new_dir = self.temp_path / "new" / "nested" / "dir"
        
        result = self.fm.ensure_directory(new_dir)
        self.assertTrue(result)
        self.assertTrue(new_dir.exists())
        self.assertTrue(new_dir.is_dir())
        print("✓ test_ensure_directory 通过")
    
    def test_list_directory(self):
        """测试列出目录内容"""
        (self.temp_path / "file1.txt").write_text("1")
        (self.temp_path / "file2.txt").write_text("2")
        (self.temp_path / "subdir").mkdir()
        
        items = self.fm.list_directory(self.temp_path)
        
        self.assertEqual(len(items), 3)
        names = [item["name"] for item in items]
        self.assertIn("file1.txt", names)
        self.assertIn("file2.txt", names)
        self.assertIn("subdir", names)
        print("✓ test_list_directory 通过")
    
    def test_list_directory_with_pattern(self):
        """测试列出目录内容（带模式）"""
        (self.temp_path / "file1.txt").write_text("1")
        (self.temp_path / "file2.py").write_text("2")
        
        items = self.fm.list_directory(self.temp_path, pattern="*.txt")
        
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "file1.txt")
        print("✓ test_list_directory_with_pattern 通过")
    
    # ============================================================
    # 文件信息测试
    # ============================================================
    
    def test_get_file_info(self):
        """测试获取文件信息"""
        test_file = self.temp_path / "info.txt"
        test_file.write_text("content")
        
        info = self.fm.get_file_info(test_file)
        
        self.assertEqual(info["name"], "info.txt")
        self.assertEqual(info["size"], 7)
        self.assertFalse(info["is_dir"])
        self.assertEqual(info["extension"], ".txt")
        print("✓ test_get_file_info 通过")
    
    # ============================================================
    # 路径安全测试
    # ============================================================
    
    def test_path_security_outside_workdir(self):
        """测试路径安全：工作目录外的普通文件可以访问（类似 VSCode 设计）
        
        注意：当前设计允许访问工作目录外的文件，只拒绝系统关键目录。
        如果文件不存在，会抛出 FileNotFoundError 而非 PathSecurityError。
        """
        outside_path = self.temp_path.parent / "outside.txt"
        
        # 工作目录外的不存在文件应抛出 FileNotFoundError
        with self.assertRaises(FileNotFoundError):
            self.fm.read_file(outside_path)
        print("✓ test_path_security_outside_workdir 通过")
    
    def test_path_security_system_directory(self):
        """测试路径安全：系统关键目录应被拒绝"""
        from infrastructure.persistence.file_manager import PathSecurityError
        import platform
        
        # 根据操作系统选择系统目录
        if platform.system() == "Windows":
            system_path = Path("C:/Windows/System32/config/test.txt")
        else:
            system_path = Path("/etc/passwd")
        
        with self.assertRaises(PathSecurityError):
            self.fm.read_file(system_path)
        print("✓ test_path_security_system_directory 通过")
    
    # ============================================================
    # 临时文件测试
    # ============================================================
    
    def test_create_temp_file(self):
        """测试创建临时文件"""
        content = "temp content"
        
        temp_path = self.fm.create_temp_file(content, prefix="test_", suffix=".tmp")
        
        self.assertTrue(temp_path.exists())
        self.assertEqual(temp_path.read_text(), content)
        self.assertTrue(temp_path.name.startswith("test_"))
        self.assertTrue(temp_path.name.endswith(".tmp"))
        print("✓ test_create_temp_file 通过")
    
    def test_cleanup_temp_files(self):
        """测试清理临时文件"""
        temp_path = self.fm.create_temp_file("temp", prefix="old_")
        
        old_time = time.time() - 25 * 60 * 60
        os.utime(temp_path, (old_time, old_time))
        
        deleted = self.fm.cleanup_temp_files()
        
        self.assertEqual(deleted, 1)
        self.assertFalse(temp_path.exists())
        print("✓ test_cleanup_temp_files 通过")


if __name__ == "__main__":
    print("=" * 60)
    print("FileManager 单元测试")
    print("=" * 60)
    
    unittest.main(verbosity=2)
