from dataclasses import dataclass, field


# Titles and accessions verified in the public NASA PSI repository.
INVESTIGATION_TITLES = {
    "PSI-10": "Advanced Combustion via Microgravity Experiments / Flame Design",
    "PSI-20": "Advanced Combustion via Microgravity Experiments - Burning Rate Emulator",
    "PSI-21": "Advanced Combustion via Microgravity Experiments / Coflow Laminar Diffusion Flame",
    "PSI-22": "Advanced Combustion via Microgravity Experiments Electric-Field Effects on Laminar Diffusion Flames",
    "PSI-23": "Advanced Combustion via Microgravity Experiments-Structure and Response of Spherical Diffusion Flames",
    "PSI-25": "Burning and Suppression of Solids - II",
    "PSI-26": "Burning and Suppression of Solids",
    "PSI-39": "Cool Flames Investigation",
    "PSI-47": "Dust and Aerosol Measurement Feasibility Test / Dust and Aerosol Measurement Feasibility Test-2",
    "PSI-68": "Flame Extinguishment Experiment - 2",
    "PSI-69": "Flame Extinguishment Experiment",
    "PSI-98": "Spacecraft Fire Safety Experiment-I",
    "PSI-99": "Spacecraft Fire Experiment-II",
    "PSI-100": "Spacecraft Fire Experiment-III",
    "PSI-101": "Smoke Aerosol Measurement Experiment-Reflight",
    "PSI-102": "Smoke and Aerosol Measurement Experiment",
    "PSI-106": "Structure and Liftoff In Combustion Experiment",
    "PSI-107": "Smoke Point In Co-flow Experiment",
    "PSI-159": "Advanced Combustion via Microgravity Experiments / Cool Flames Investigation with Gases",
}


@dataclass(frozen=True)
class TableProfile:
    observations: str
    quantities: tuple[str, ...] = ()
    counts: tuple[str, ...] = ()
    units: dict[str, str] = field(default_factory=dict)
    identifiers: tuple[str, ...] = ()
    required_identifier: str | None = None
    scope: str = "experimental_summary"
    quantitative_context: tuple[str, ...] = ()
    quantitative_values: tuple[str, ...] = ()
    quantitative_blockers: tuple[str, ...] = ()


FIRE_SAMPLE_QUANTITIES = (
    "Sample Width (cm)", "Air Flow (cm/s)", "Ignition Power (W)",
    "Ignition Time (s)", "Burn Time (s)",
)

PROFILES = {
    ("PSI-10", "Flame Design_Inverse Flame"): TableProfile(
        "Trial summaries with flow, pressure and computed quantities. RAMP and LOW O2 are annotations.",
        quantities=("XO2", "mO2 (mg/s)", "mN2 (mg/s)", "mtot (mg/s)", "XC2H4 initial",
                    "XC2H4 final", "pinit (atm)", "pfinal (atm)", "pmean (atm)", "mean Zst", "Tad (K)"),
        identifiers=("Test",), required_identifier="Test",
        quantitative_context=("Test",), quantitative_values=("pinit (atm)", "pfinal (atm)"),
    ),
    ("PSI-10", "Flame Design_Normal Flame"): TableProfile(
        "Trial summaries. RAMP and RAMPED are annotations. Some final O2 and pressure cells are blank.",
        quantities=("Xfuel", "mfuel (mg/s)", "mN2 (mg/s)", "mtot (mg/s)", "XO2 (init)",
                    "XO2 (final)", "pinit (atm)", "pfinal (atm)", "pmean (atm)", "mean Zst", "Tad (K)"),
        identifiers=("Test",), required_identifier="Test",
        quantitative_context=("Test", "Fuel"), quantitative_values=("pinit (atm)", "pfinal (atm)"),
    ),
    ("PSI-20", "ACME BRE"): TableProfile(
        "Summary by day with ignition counts and approximate O2 settings, per source notes. "
        "Chamber pressures and individual trial measurements are unavailable.",
        quantities=("Burner Size (mm)", "Oxygen Conc (percent)"), counts=("Flames Ignited",),
        scope="conditions_and_counts",
    ),
    ("PSI-21", "CLD Flame"): TableProfile(
        "Summary by day with ignition counts, fuel ranges and MFC maximum settings. "
        "The notes declare slpm on a nitrogen basis. Some fuel labels differ from the test types. "
        "Individual trial measurements are unavailable.",
        quantities=("Fuel MFC", "N2 MFC", "Fuel conc. Range"), counts=("Flames ignited",),
        units={"Fuel MFC": "slpm", "N2 MFC": "slpm", "Fuel conc. Range": "%"},
        identifiers=("Test Day",), required_identifier="Test Day", scope="conditions_and_counts",
    ),
    ("PSI-22", "ACME E-FIELD Flames"): TableProfile(
        "Summary by day. Sparse concentration rows have no day identifier. "
        "Individual trial measurements are unavailable.",
        quantities=("Fuel Conc",), counts=("Flames Ignited",), units={"Fuel Conc": "%"},
        identifiers=("Test Day",), required_identifier="Test Day", scope="conditions_and_counts",
    ),
    ("PSI-23", "ACME s-Flame"): TableProfile(
        "Summary by day with ignition counts and approximate atmosphere descriptions. "
        "N3 through N6 labels are ambiguous. Individual trial measurements are unavailable.",
        counts=("Flames Ignited*",), identifiers=("Test Day*",), required_identifier="Test Day*",
        scope="conditions_and_counts",
    ),
    ("PSI-25", "BASS-II"): TableProfile(
        "Gas readings and experiment settings. The NASA technical report supports the GMT and sensor checks.",
        quantitative_context=("Test #",),
        quantitative_values=("Initial CO2 % by vol", "Final CO2 % by vol"),
        quantitative_blockers=("initial_co2_outside_sensor_range", "final_co2_outside_sensor_range"),
    ),
    ("PSI-26", "BASS"): TableProfile(
        "Test identifiers, dates and sample descriptions only. Reused sample numbers are retained.",
        identifiers=("As Run Test #", "Test #"), required_identifier="As Run Test #",
        scope="metadata_only",
    ),
    ("PSI-39", "CFI"): TableProfile(
        "Experimental conditions without combustion outcome measurements. "
        "The gas composition columns do not declare units or a basis.",
        quantities=("Pressure", "Oxygen", "Nitrogen", "Helium"), units={"Pressure": "atm"},
        identifiers=("Flex Number", "CIR "), required_identifier="Flex Number", scope="conditions_only",
    ),
    ("PSI-47", "DAFT"): TableProfile(
        "Session, hardware, material and sampling location only. Aerosol measurements are unavailable.",
        identifiers=("Session Name",), scope="metadata_only",
    ),
    ("PSI-68", "Flex2"): TableProfile(
        "Ranges and alternative settings by fuel. Trial-level readings and outcomes are unavailable.",
        quantities=("Initial Droplet Diameter (mm)", "Oxygen Mole Fraction", "Ambient Pressure (atm)",
                    " Ambient Temperature (C)", "Flow Velocity (cm/s)"),
        units={"Oxygen Mole Fraction": "mole fraction"}, scope="conditions_only",
    ),
    ("PSI-69", "FLEX"): TableProfile(
        "Droplet combustion results. Burning rate keeps the source unit mm. "
        "Ambient composition labels O, N, CO and He are transcribed as supplied.",
        quantitative_context=("FLEX Test #", "Fuel"), quantitative_values=("Burn time; s",),
    ),
    ("PSI-98", "SAFFIRE-1"): TableProfile(
        "Two burn summaries and two pre-test visualization references. O2 includes a range and an approximation.",
        quantities=("Sample Thickness (cm)", "Sample Length (cm)", "Percent O2", *FIRE_SAMPLE_QUANTITIES),
        units={"Percent O2": "%"}, identifiers=("Sample Number ",),
        quantitative_context=("Sample Number ", "Material"), quantitative_values=("Burn Time (s)",),
    ),
    ("PSI-99", "SAFFIRE-2"): TableProfile(
        "Nine sample summaries, two pre-test references and four note rows. "
        "Thickness uses mixed units and three cells read 037 mm. "
        "The ?-g Spread Length field contains rates in mm/s and remains untyped.",
        quantities=("Sample Length ", "Percent O2 (Note 1)", "?-g Burn Length",
                    "1-g Burn Length", "1-g Spread Rate", *FIRE_SAMPLE_QUANTITIES),
        units={"Sample Length ": "cm", "Percent O2 (Note 1)": "%", "?-g Burn Length": "cm",
               "1-g Burn Length": "cm", "1-g Spread Rate": "mm/s"},
        identifiers=("Sample Number",),
        quantitative_context=("Sample Number", "Material"), quantitative_values=("Burn Time (s)",),
    ),
    ("PSI-100", "SAFFIRE-3"): TableProfile(
        "Two sample and flow configurations with camera identifiers. Burn outcomes are unavailable.",
        quantities=("Sample Thickness", "Sample Length", "Sample Width", "Air Flow "),
        units={"Sample Thickness": "cm", "Sample Length": "cm", "Sample Width": "cm",
               "Air Flow ": "cm/s"},
        identifiers=("Sample Number ",), scope="conditions_only",
    ),
    ("PSI-101", "SAME-R"): TableProfile(
        "Experimental settings and timing summaries. The Rt/R0 ratio is retained as labeled. "
        "Detailed aerosol measurements are unavailable.",
        quantities=("Inlet velocity (cm/s)", "Rt/R0", "Duration (sec)", "Primary aging time (sec)",
                    "Primary mixing time (sec)", "Net aging time (sec)"),
        identifiers=("SAME Test #",), required_identifier="SAME Test #", scope="conditions_only",
    ),
    ("PSI-102", "SAME"): TableProfile(
        "Four rows list quantities. Four reference the conditions of rows 1-4 in the material text.",
        quantities=("Air Flow (cm/s)", "Weight loss rate (mg/min)", "Aging Duration (minutes)"),
        identifiers=("Sample #",), required_identifier="Sample #",
        quantitative_context=("Sample #", "Sample Material  "),
        quantitative_values=("Weight loss rate (mg/min)",),
    ),
    ("PSI-106", "Slice"): TableProfile(
        "A date and fuel schedule with embedded test notes. Outcome measurements are unavailable.",
        scope="metadata_only",
    ),
    ("PSI-107", "Spice"): TableProfile(
        "Ignition and flame-off labels, nozzle and rate data. "
        "Repeated time tuples can represent different conditions. Time strings remain unparsed. "
        "Signed air rates are preserved without inferring direction or correcting their sign.",
        quantities=("Nozzle (mm)", "Fuel Rate (sccm)", "Fuel Rate (mg/s)",
                    "HC Fuel Rate (mg/s)", "Air Rate (cm/s)"),
        quantitative_context=("Fuel",), quantitative_values=("Nozzle (mm)", "Fuel Rate (mg/s)"),
    ),
    ("PSI-159", "CFI-G_Inverse Flames"): TableProfile(
        "Trial summaries followed by empty records. Approximate pressure and spreadsheet errors "
        "are preserved as supplied.",
        quantities=("Xf  before test", "Xf  after test", "approx p (bar)", "XO2", "HC burnrate (mg/s)",
                    "O2 flow rate (mg/s)", "Tad (K)", "Zst", "burn time (sec)",
                    "Peak burner Temp (C)", "Peak burner temp (K)"),
        identifiers=("Test",), required_identifier="Test",
        quantitative_context=("Test", "Fuel"), quantitative_values=("burn time (sec)",),
    ),
    ("PSI-159", "CFI-G_Normal Flames"): TableProfile(
        "Trial summaries including cool-flame comments. Approximate pressure and spreadsheet errors "
        "are preserved as supplied.",
        quantities=(" XO2 before test", "XO2  after test", "approx p (bar)", "Xf", "mHC (mg/s)",
                    "Tad (K)", "Zst", "burn time (sec)", "Peak burner T (C )"),
        identifiers=("Test",), required_identifier="Test",
        quantitative_context=("Test", "Fuel"), quantitative_values=("burn time (sec)",),
    ),
}
