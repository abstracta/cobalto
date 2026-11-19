"""Records shared by the modules of the CLI."""
from dataclasses import dataclass, field


@dataclass
class SuiteRef:
    """A suite that takes part in a run: its program id, the file it comes
    from and its description."""
    id: str
    file: str
    description: str = ""


@dataclass
class Generated:
    """What generating the suites produced, and what reporting a run needs to
    know about them."""
    suites: list = field(default_factory=list)          # SuiteRef, in run order
    gen_files: list = field(default_factory=list)       # generated COBOL, one per DSL suite
    legacy_files: list = field(default_factory=list)    # hand-written test programs
    sources: list = field(default_factory=list)         # programs under test (instrumented copies with coverage)
    driver: str = ""                                    # path of the generated driver
    linemaps: dict = field(default_factory=dict)        # generated file -> origin of each line
    inprog: dict = field(default_factory=dict)          # suite id -> file name of the original program
    case_kinds: dict = field(default_factory=dict)      # (suite id, case name) -> (kind, reasons)
    cov_map: dict = field(default_factory=dict)         # PROGRAM-ID -> coverage map (coverage.Plan.to_json)

    @property
    def tests(self):
        return self.gen_files + self.legacy_files
