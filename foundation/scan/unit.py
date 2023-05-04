import datajoint as dj
from djutils import merge, row_method
from foundation.scan.experiment import Scan
from foundation.schemas.pipeline import pipe_fuse, pipe_shared, resolve_pipe
from foundation.schemas import scan as schema


# -------------- Unit Set --------------


@schema.set
class UnitSet:
    keys = [pipe_fuse.ScanSet.Unit]
    name = "units"
    comment = "scan unit set"
    part_name = "unit"


# -------------- Unit Filter --------------

# -- Filter Types --


@schema.filter_lookup
class UnitMaskType:
    ftype = pipe_fuse.ScanSet.Unit
    definition = """
    -> pipe_shared.PipelineVersion
    -> pipe_shared.SegmentationMethod
    -> pipe_shared.ClassificationMethod
    -> pipe_shared.MaskType
    """

    @row_method
    def filter(self, units):
        pipe = resolve_pipe(units)
        key = merge(
            units,
            self.proj(target="type"),
            pipe.MaskClassification.Type * pipe.ScanSet.Unit,
        )
        return units & (key & "type = target")


# -- Filter --


@schema.filter_link
class UnitFilterLink:
    links = [UnitMaskType]
    name = "unit_filter"
    comment = "scan unit filter"


# -- Filter Set --


@schema.filter_link_set
class UnitFilterSet:
    link = UnitFilterLink
    name = "unit_filters"
    comment = "scan unit filter set"


# -- Computed Filter --


@schema.computed
class FilteredUnits:
    definition = """
    -> Scan
    -> UnitFilterSet
    ---
    -> UnitSet
    """

    @property
    def key_source(self):
        return Scan.proj() * UnitFilterSet.proj() & pipe_fuse.ScanDone

    def make(self, key):
        # scan units
        units = pipe_fuse.ScanSet.Unit & key

        # filter units
        units = (UnitFilterSet & key).filter(units)

        # insert unit set
        unit_set = UnitSet.fill(units, prompt=False)

        # insert key
        self.insert1(dict(key, **unit_set))

    def fill_units(self, spike_key={"spike_method": 6}):
        """
        Parameters
        ----------
        spike_key : datajoint.key
            key for pipe_shared.SpikeMethod
        """
        from foundation.recording.trace import ScanUnit, TraceLink, TraceHomogeneous, TraceTrials

        # scan unit traces
        units = UnitSet.Member & self
        units = units * (pipe_shared.SpikeMethod & spike_key).proj()
        ScanUnit.insert(units, skip_duplicates=True, ignore_extra_fields=True)

        # trace link
        TraceLink.fill()

        # compute trace
        key = TraceLink.ScanUnit & units
        TraceHomogeneous.populate(key, display_progress=True, reserve_jobs=True)
        TraceTrials.populate(key, display_progress=True, reserve_jobs=True)
