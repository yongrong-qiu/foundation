import os
import numpy as np
import datajoint as dj
from djutils import merge, Files
from tempfile import TemporaryDirectory
from operator import add
from functools import reduce
from tqdm import tqdm
from foundation.recording import trial, trace, sample
from foundation.utility import resample
from foundation.schemas import recording as schema


@schema.computed
class CachedTraces(Files):
    store = "scratch09"
    definition = """
    -> trace.TraceSet
    -> resample.RateLink
    -> resample.OffsetLink
    -> resample.ResampleLink
    -> trial.TrialLink
    ---
    traces      : filepath@scratch09    # npy file, [samples, traces]
    finite      : bool                  # all values finite
    """

    @property
    def scan_keys(self):
        from foundation.recording.scan import (
            ScanTrialSet,
            ScanUnitSet,
            ScanModulationSet,
            ScanPerspectiveSet,
        )

        return [
            trial.TrialSet.Member * ScanTrialSet * ScanUnitSet,
            trial.TrialSet.Member * ScanTrialSet * ScanPerspectiveSet,
            trial.TrialSet.Member * ScanTrialSet * ScanModulationSet,
        ]

    @property
    def keys(self):
        keys = self.scan_keys
        keys = reduce(add, [dj.U("traces_id", "trial_id") & key for key in keys])
        keys = keys * (resample.RateLink * resample.OffsetLink * resample.ResampleLink).proj()
        return keys - self

    @property
    def key_source(self):
        key = dj.U("traces_id", "rate_id", "offset_id", "resample_id")
        key = key.aggr(self.keys, trial_id="min(trial_id)")
        return key * trial.TrialLink.proj()

    def make(self, key):
        # remove trial_id from key
        key.pop("trial_id")

        # fetch all trials for trace set, ordered by trial_id
        trials = self.keys & key
        trials = merge(trials, sample.TrialSamples & key)
        trial_ids, samples = trials.fetch("trial_id", "samples", order_by="trial_id")

        # fetch all traces for trace set, orderd by member_id of trace set
        traces = (trace.TraceSet & key).members
        traces = merge(traces, sample.TraceSamples & key)
        trace_keys = traces.fetch("KEY", order_by="member_id")

        with TemporaryDirectory() as tmpdir:

            # temporary memmap
            memmap = np.memmap(
                filename=os.path.join(tmpdir, "traces.dat"),
                shape=(len(trace_keys), sum(samples)),
                dtype=np.float32,
                mode="w+",
            )

            # write traces to memmap
            for i, trace_key in enumerate(tqdm(trace_keys, desc="Traces")):

                df = (sample.TraceSamples & trace_key).samples.loc[trial_ids]
                memmap[i] = np.concatenate(df.trace.values).astype(np.float32)
                memmap.flush()

            # read traces from memmap and save to file
            j = 0
            for trial_id, trial_n in zip(trial_ids, tqdm(samples, desc="Trials")):

                _traces = memmap[:, j : j + trial_n].T
                _finite = bool(np.isfinite(_traces).all())

                _key = dict(key, trial_id=trial_id)
                _dir = self.tuple_dir(_key, create=True)
                _file = os.path.join(_dir, "traces.npy")

                np.save(_file, _traces)
                self.insert1(dict(_key, traces=_file, finite=_finite))

                j += trial_n
