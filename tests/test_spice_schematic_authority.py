from textwrap import dedent

from domain.simulation.spice.parser import SpiceParser
from domain.simulation.spice.schematic_builder import SpiceSchematicBuilder
from presentation.panels.simulation.simulation_frontend_state_serializer import (
    SimulationFrontendStateSerializer,
)


def test_parser_assigns_stable_pin_identities_to_inline_opamp_subckt_instance() -> None:
    content = dedent(
        """
        .subckt IDEAL_OPAMP plus minus out vcc vee
        E1 nint 0 plus minus 1e6
        R1 out nint 1
        .ends IDEAL_OPAMP
        XU1 0 inv out vcc vee IDEAL_OPAMP
        """
    ).strip()

    document = SpiceParser().parse_content(content, "inline_opamp.cir")

    assert len(document.components) == 1
    component = document.components[0]
    assert component.primitive_kind == "opamp"
    assert component.symbol_kind == "opamp"
    assert component.subckt_name == "IDEAL_OPAMP"
    assert component.resolved_model_name == "IDEAL_OPAMP"
    assert component.semantic_roles == ["opamp"]
    assert [pin.name for pin in component.pins] == ["plus", "minus", "out", "vcc", "vee"]
    assert [pin.node_id for pin in component.pins] == ["0", "inv", "out", "vcc", "vee"]
    assert component.pin_roles == {
        "plus": "input_plus",
        "minus": "input_minus",
        "out": "output",
        "vcc": "power_positive",
        "vee": "power_negative",
    }
    assert len(document.subcircuits) == 1
    assert document.subcircuits[0].primitive_kind == "opamp"
    assert document.subcircuits[0].scope_path == []


def test_parser_resolves_lt1001_from_backend_library_registry() -> None:
    content = "XU1 0 inv out vcc vee LT1001"

    document = SpiceParser().parse_content(content, "lt1001_instance.cir")

    assert len(document.components) == 1
    component = document.components[0]
    assert component.primitive_kind == "opamp"
    assert component.symbol_kind == "opamp"
    assert component.subckt_name == "LT1001"
    assert component.resolved_model_name == "LT1001"
    assert [pin.name for pin in component.pins] == ["plus", "minus", "vcc", "vee", "out"]
    assert component.primitive_source.lower().endswith("ltc.lib")


def test_builder_absorbs_primitive_subckt_internals_before_frontend() -> None:
    content = dedent(
        """
        .subckt IDEAL_OPAMP plus minus out vcc vee
        E1 nint 0 plus minus 1e6
        R1 out nint 1
        .ends IDEAL_OPAMP
        XU1 0 inv out vcc vee IDEAL_OPAMP
        RFB out inv 10k
        """
    ).strip()

    document = SpiceParser().parse_content(content, "builder_absorption.cir")
    payload = SpiceSchematicBuilder().build_document(document, source_text=content)

    assert [component["instance_name"] for component in payload["components"]] == ["XU1", "RFB"]
    assert payload["subcircuits"] == []
    assert all(net["name"] != "nint" for net in payload["nets"])


def test_serializer_preserves_authoritative_primitive_fields() -> None:
    content = dedent(
        """
        .subckt IDEAL_OPAMP plus minus out vcc vee
        E1 nint 0 plus minus 1e6
        .ends IDEAL_OPAMP
        XU1 0 inv out vcc vee IDEAL_OPAMP
        """
    ).strip()

    document = SpiceParser().parse_content(content, "serialize_opamp.cir")
    schematic_document = SpiceSchematicBuilder().build_document(document, source_text=content)
    payload = SimulationFrontendStateSerializer().serialize_schematic_document(schematic_document)

    assert len(payload["components"]) == 1
    component = payload["components"][0]
    assert component["primitive_kind"] == "opamp"
    assert component["subckt_name"] == "IDEAL_OPAMP"
    assert component["resolved_model_name"] == "IDEAL_OPAMP"
    assert component["semantic_roles"] == ["opamp"]
    assert component["pin_roles"] == {
        "plus": "input_plus",
        "minus": "input_minus",
        "out": "output",
        "vcc": "power_positive",
        "vee": "power_negative",
    }
    assert component["port_side_hints"] == {
        "plus": "left",
        "minus": "left",
        "out": "right",
        "vcc": "top",
        "vee": "bottom",
    }
