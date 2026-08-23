from textwrap import dedent
from domain.simulation.spice.bundled_opamp_registry import iter_curated_bundled_opamp_model_names
from domain.simulation.spice.bundled_subcircuit_catalog import load_bundled_subcircuit_catalog
from domain.simulation.spice.parser import SpiceParser
from domain.simulation.spice.schematic_builder import SpiceSchematicBuilder
from domain.simulation.spice.source_closure import collect_spice_source_closure

def _deck(body: str) -> str:
    return f'schematic authority test\n{body.strip()}\n.end\n'

def test_parser_assigns_stable_pin_identities_to_inline_opamp_subckt_instance() -> None:
    content = _deck(dedent('\n        .subckt IDEAL_OPAMP plus minus out vcc vee\n        E1 nint 0 plus minus 1e6\n        R1 out nint 1\n        .ends IDEAL_OPAMP\n        XU1 0 inv out vcc vee IDEAL_OPAMP\n        '))
    document = SpiceParser().parse_content(content, 'inline_opamp.cir')
    assert len(document.components) == 1
    component = document.components[0]
    assert component.primitive_kind == 'opamp'
    assert component.symbol_kind == 'opamp'
    assert component.subckt_name == 'IDEAL_OPAMP'
    assert component.resolved_model_name == 'IDEAL_OPAMP'
    assert component.semantic_roles == ['opamp']
    assert [pin.name for pin in component.pins] == ['plus', 'minus', 'out', 'vcc', 'vee']
    assert [pin.node_id for pin in component.pins] == ['0', 'inv', 'out', 'vcc', 'vee']
    assert component.pin_roles == {'plus': 'input_plus', 'minus': 'input_minus', 'out': 'output', 'vcc': 'power_positive', 'vee': 'power_negative'}
    assert len(document.subcircuits) == 1
    assert document.subcircuits[0].primitive_kind == 'opamp'
    assert document.subcircuits[0].scope_path == []

def test_curated_bundled_opamp_registry_only_references_existing_subckts() -> None:
    bundled_subckt_names = {header.name for header in load_bundled_subcircuit_catalog()}
    assert set(iter_curated_bundled_opamp_model_names()).issubset(bundled_subckt_names)

def test_parser_resolves_lt1001_from_backend_library_registry() -> None:
    content = _deck('XU1 0 inv out vcc vee LT1001')
    document = SpiceParser().parse_content(content, 'lt1001_instance.cir')
    assert len(document.components) == 1
    component = document.components[0]
    assert component.primitive_kind == 'opamp'
    assert component.symbol_kind == 'opamp'
    assert component.subckt_name == 'LT1001'
    assert component.resolved_model_name == 'LT1001'
    assert [pin.name for pin in component.pins] == ['plus', 'minus', 'vcc', 'vee', 'out']
    assert component.primitive_source.lower().endswith('ltc.lib')

def test_parser_keeps_subckt_name_when_x_instance_has_trailing_params() -> None:
    content = _deck('XU1 plus minus out vcc vee CUSTOM_AMP gain=2 temp=27')
    document = SpiceParser().parse_content(content, 'x_with_params.cir')
    component = document.components[0]
    assert component.model_name == 'CUSTOM_AMP'
    assert component.subckt_name == 'CUSTOM_AMP'
    assert [pin.node_id for pin in component.pins] == ['plus', 'minus', 'out', 'vcc', 'vee']

def test_parser_resolves_lt6201_from_curated_bundled_registry() -> None:
    content = _deck('XU1 nplus nminus nout vcc vee LT6201')
    document = SpiceParser().parse_content(content, 'lt6201_instance.cir')
    component = document.components[0]
    assert component.primitive_kind == 'opamp'
    assert [pin.name for pin in component.pins] == ['plus', 'minus', 'out', 'vcc', 'vee']
    assert component.pin_roles == {'plus': 'input_plus', 'minus': 'input_minus', 'out': 'output', 'vcc': 'power_positive', 'vee': 'power_negative'}
    assert component.primitive_source.lower().endswith('ltc2.lib')

def test_parser_resolves_ltc6247_output_first_layout_from_curated_registry() -> None:
    content = _deck('XU1 out vee plus minus vcc LTC6247')
    document = SpiceParser().parse_content(content, 'ltc6247_instance.cir')
    component = document.components[0]
    assert component.primitive_kind == 'opamp'
    assert [pin.name for pin in component.pins] == ['out', 'vee', 'plus', 'minus', 'vcc']
    assert component.pin_roles == {'out': 'output', 'vee': 'power_negative', 'plus': 'input_plus', 'minus': 'input_minus', 'vcc': 'power_positive'}
    assert component.primitive_source.lower().endswith('ltc7.lib')

def test_parser_resolves_ltc6081_auxiliary_pin_from_curated_registry() -> None:
    content = _deck('XU1 plus minus vcc vee out shdn LTC6081')
    document = SpiceParser().parse_content(content, 'ltc6081_instance.cir')
    component = document.components[0]
    assert component.primitive_kind == 'opamp'
    assert [pin.name for pin in component.pins] == ['plus', 'minus', 'vcc', 'vee', 'out', 'aux_1']
    assert component.pin_roles == {'plus': 'input_plus', 'minus': 'input_minus', 'vcc': 'power_positive', 'vee': 'power_negative', 'out': 'output', 'aux_1': 'auxiliary'}

def test_parser_resolves_lm308_legacy_auxiliary_layout_from_curated_registry() -> None:
    content = _deck('XU1 plus minus vcc vee out aux1 aux2 LM308')
    document = SpiceParser().parse_content(content, 'lm308_instance.cir')
    component = document.components[0]
    assert component.primitive_kind == 'opamp'
    assert [pin.name for pin in component.pins] == ['plus', 'minus', 'vcc', 'vee', 'out', 'aux_1', 'aux_2']
    assert component.pin_roles == {'plus': 'input_plus', 'minus': 'input_minus', 'vcc': 'power_positive', 'vee': 'power_negative', 'out': 'output', 'aux_1': 'auxiliary', 'aux_2': 'auxiliary'}

def test_parser_does_not_misclassify_bundled_comparator_as_opamp() -> None:
    content = _deck('XU1 plus minus out vcc vee LT1017')
    document = SpiceParser().parse_content(content, 'lt1017_instance.cir')
    component = document.components[0]
    assert component.primitive_kind == ''
    assert component.symbol_kind == 'subckt_block'
    assert [pin.name for pin in component.pins] == ['port_1', 'port_2', 'port_3', 'port_4', 'port_5']

def test_builder_absorbs_primitive_subckt_internals_before_frontend() -> None:
    content = _deck(dedent('\n        .subckt IDEAL_OPAMP plus minus out vcc vee\n        E1 nint 0 plus minus 1e6\n        R1 out nint 1\n        .ends IDEAL_OPAMP\n        XU1 0 inv out vcc vee IDEAL_OPAMP\n        RFB out inv 10k\n        '))
    document = SpiceParser().parse_content(content, 'builder_absorption.cir')
    payload = SpiceSchematicBuilder().build_document(document, source_text=content)
    assert [component['instance_name'] for component in payload['components']] == ['XU1', 'RFB']
    assert payload['subcircuits'] == []
    assert all((net['name'] != 'nint' for net in payload['nets']))

def test_parser_obeys_title_control_and_end_boundaries() -> None:
    content = 'R title that must not become a resistor\n// supported ngspice comment\n.control\nRfake out 0 1\n.endc\nR1 out 0 1k\n.end\nRafter out 0 2k\n'
    document = SpiceParser().parse_content(content, 'boundaries.cir')
    assert [component.instance_name for component in document.components] == ['R1']

def test_parser_unifies_ngspice_gnd_alias_with_node_zero() -> None:
    document = SpiceParser().parse_content(_deck('R1 OUT GND 1k\nR2 out 0 2k'), 'ground_alias.cir')
    assert document.components[0].node_ids == ['out', '0']
    assert document.components[1].node_ids == ['out', '0']

def test_subcircuit_params_are_not_misreported_as_ports() -> None:
    content = _deck('.subckt FILTER in out PARAMS: gain=2 corner=1k\nR1 in out 1k\n.ends FILTER\nX1 src dst FILTER gain=3')
    document = SpiceParser().parse_content(content, 'subckt_params.cir')
    assert document.subcircuits[0].port_names == ['in', 'out']
    assert document.components[0].model_name == 'FILTER'
    assert [pin.node_id for pin in document.components[0].pins] == ['src', 'dst']

def test_semiconductor_models_are_case_insensitive_and_keep_real_terminal_counts() -> None:
    content = _deck('.model FancyP PNP\n.model FancyN NMOS\nQ1 c b e substrate fancyp\nM1 d g s body FANCYN')
    document = SpiceParser().parse_content(content, 'semiconductors.cir')
    bjt, mos = document.components
    assert bjt.symbol_variant == 'pnp'
    assert [pin.name for pin in bjt.pins] == ['collector', 'base', 'emitter', 'substrate']
    assert bjt.model_name == 'fancyp'
    assert mos.symbol_variant == 'nmos'
    assert [pin.name for pin in mos.pins] == ['drain', 'gate', 'source', 'body']
    assert mos.model_name == 'FANCYN'

def test_four_terminal_bjt_does_not_require_model_registry_guessing() -> None:
    document = SpiceParser().parse_content(_deck('Q1 collector base emitter substrate ExternalVendorModel'), 'external_bjt.cir')
    component = document.components[0]
    assert component.model_name == 'ExternalVendorModel'
    assert component.node_ids == ['collector', 'base', 'emitter', 'substrate']
    assert [pin.name for pin in component.pins] == ['collector', 'base', 'emitter', 'substrate']

def test_u_device_is_urc_not_a_subcircuit_and_transmission_line_has_four_terminals() -> None:
    content = _deck('U1 in out 0 URCMOD L=50u\nT1 in 0 out 0 Z0=50 TD=10n\nK1 L1 L2 0.99')
    document = SpiceParser().parse_content(content, 'distributed.cir')
    urc, transmission_line, coupling = document.components
    assert urc.symbol_kind == 'distributed_rc_line'
    assert urc.subckt_name == ''
    assert [pin.node_id for pin in urc.pins] == ['in', 'out', '0']
    assert [pin.node_id for pin in transmission_line.pins] == ['in', '0', 'out', '0']
    assert coupling.symbol_kind == 'mutual_inductor'
    assert coupling.node_ids == []

def test_inline_opamp_v_supply_names_are_power_rails_not_signal_inputs() -> None:
    content = _deck('.subckt IDEAL_OPAMP in+ in- out v+ v-\n.ends IDEAL_OPAMP\nX1 plus minus out vcc vee IDEAL_OPAMP')
    document = SpiceParser().parse_content(content, 'opamp_rails.cir')
    assert document.components[0].pin_roles == {'plus': 'input_plus', 'minus': 'input_minus', 'out': 'output', 'vcc': 'power_positive', 'vee': 'power_negative'}

def test_source_graph_rejects_ambiguous_active_model_definitions(tmp_path) -> None:
    source_path = tmp_path / 'ambiguous.cir'
    first_library = tmp_path / 'first.lib'
    second_library = tmp_path / 'second.lib'
    source_path.write_text('title\n.include first.lib\n.include second.lib\nM1 drain gate 0 0 SHARED_DEVICE\n.op\n.end\n', encoding='utf-8')
    first_library.write_text('.model SHARED_DEVICE NMOS(level=1)\n', encoding='utf-8')
    second_library.write_text('.model SHARED_DEVICE PMOS(level=1)\n', encoding='utf-8')
    graph = collect_spice_source_closure(source_path)
    document = SpiceParser().parse_source_graph(graph)
    main_mos = next((component for component in document.components if component.instance_name == 'M1'))
    assert main_mos.symbol_variant == 'mos'
    conflicts = [
        error
        for error in document.parse_errors
        if 'shared_device' in error.message.lower()
    ]
    assert len(conflicts) == 1
    assert conflicts[0].source_file == graph.main_blob.key
    assert 'first.lib' in conflicts[0].message.lower()
    assert 'second.lib' in conflicts[0].message.lower()

def test_active_include_components_share_the_callers_electrical_scope(tmp_path) -> None:
    source_path = tmp_path / 'connected.cir'
    dependency_path = tmp_path / 'load.inc'
    source_path.write_text('title\n.include load.inc\nV1 supply 0 5\n.op\n.end\n', encoding='utf-8')
    dependency_path.write_text('RLOAD supply 0 1k\n', encoding='utf-8')
    graph = collect_spice_source_closure(source_path)
    document = SpiceParser().parse_source_graph(graph)
    schematic = SpiceSchematicBuilder().build_document(document, source_text=graph.main_blob.source_text)
    supply_nets = [net for net in schematic['nets'] if net['name'] == 'supply']
    assert len(supply_nets) == 1
    assert {connection['instance_name'] for connection in supply_nets[0]['connections']} == {'V1', 'RLOAD'}
