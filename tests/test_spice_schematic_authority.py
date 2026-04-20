from textwrap import dedent

from domain.simulation.spice.bundled_opamp_registry import iter_curated_bundled_opamp_model_names
from domain.simulation.spice.bundled_subcircuit_catalog import load_bundled_subcircuit_catalog
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


def test_curated_bundled_opamp_registry_only_references_existing_subckts() -> None:
    bundled_subckt_names = {header.name for header in load_bundled_subcircuit_catalog()}
    assert set(iter_curated_bundled_opamp_model_names()).issubset(bundled_subckt_names)


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


def test_parser_keeps_subckt_name_when_x_instance_has_trailing_params() -> None:
    content = "XU1 plus minus out vcc vee CAI_COMPAT_OPAMP_5 gain=2 temp=27"

    document = SpiceParser().parse_content(content, "x_with_params.cir")

    component = document.components[0]
    assert component.model_name == "CAI_COMPAT_OPAMP_5"
    assert component.subckt_name == "CAI_COMPAT_OPAMP_5"
    assert [pin.node_id for pin in component.pins] == ["plus", "minus", "out", "vcc", "vee"]


def test_parser_resolves_lt6201_from_curated_bundled_registry() -> None:
    content = "XU1 nplus nminus nout vcc vee LT6201"

    document = SpiceParser().parse_content(content, "lt6201_instance.cir")

    component = document.components[0]
    assert component.primitive_kind == "opamp"
    assert [pin.name for pin in component.pins] == ["plus", "minus", "out", "vcc", "vee"]
    assert component.pin_roles == {
        "plus": "input_plus",
        "minus": "input_minus",
        "out": "output",
        "vcc": "power_positive",
        "vee": "power_negative",
    }
    assert component.primitive_source.lower().endswith("ltc2.lib")


def test_parser_resolves_ltc6247_output_first_layout_from_curated_registry() -> None:
    content = "XU1 out vee plus minus vcc LTC6247"

    document = SpiceParser().parse_content(content, "ltc6247_instance.cir")

    component = document.components[0]
    assert component.primitive_kind == "opamp"
    assert [pin.name for pin in component.pins] == ["out", "vee", "plus", "minus", "vcc"]
    assert component.pin_roles == {
        "out": "output",
        "vee": "power_negative",
        "plus": "input_plus",
        "minus": "input_minus",
        "vcc": "power_positive",
    }
    assert component.primitive_source.lower().endswith("ltc7.lib")


def test_parser_resolves_ltc6081_auxiliary_pin_from_curated_registry() -> None:
    content = "XU1 plus minus vcc vee out shdn LTC6081"

    document = SpiceParser().parse_content(content, "ltc6081_instance.cir")

    component = document.components[0]
    assert component.primitive_kind == "opamp"
    assert [pin.name for pin in component.pins] == ["plus", "minus", "vcc", "vee", "out", "aux_1"]
    assert component.pin_roles == {
        "plus": "input_plus",
        "minus": "input_minus",
        "vcc": "power_positive",
        "vee": "power_negative",
        "out": "output",
        "aux_1": "auxiliary",
    }


def test_parser_resolves_lm308_legacy_auxiliary_layout_from_curated_registry() -> None:
    content = "XU1 plus minus vcc vee out aux1 aux2 LM308"

    document = SpiceParser().parse_content(content, "lm308_instance.cir")

    component = document.components[0]
    assert component.primitive_kind == "opamp"
    assert [pin.name for pin in component.pins] == ["plus", "minus", "vcc", "vee", "out", "aux_1", "aux_2"]
    assert component.pin_roles == {
        "plus": "input_plus",
        "minus": "input_minus",
        "vcc": "power_positive",
        "vee": "power_negative",
        "out": "output",
        "aux_1": "auxiliary",
        "aux_2": "auxiliary",
    }


def test_parser_does_not_misclassify_bundled_comparator_as_opamp() -> None:
    content = "XU1 plus minus out vcc vee LT1017"

    document = SpiceParser().parse_content(content, "lt1017_instance.cir")

    component = document.components[0]
    assert component.primitive_kind == ""
    assert component.symbol_kind == "subckt_block"
    assert [pin.name for pin in component.pins] == ["port_1", "port_2", "port_3", "port_4", "port_5"]


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


def test_serializer_places_auxiliary_opamp_pins_on_bottom_side() -> None:
    content = "XU1 plus minus vcc vee out shdn LTC6081"

    document = SpiceParser().parse_content(content, "serialize_ltc6081.cir")
    schematic_document = SpiceSchematicBuilder().build_document(document, source_text=content)
    payload = SimulationFrontendStateSerializer().serialize_schematic_document(schematic_document)

    component = payload["components"][0]
    assert component["port_side_hints"] == {
        "plus": "left",
        "minus": "left",
        "vcc": "top",
        "vee": "bottom",
        "out": "right",
        "aux_1": "bottom",
    }
