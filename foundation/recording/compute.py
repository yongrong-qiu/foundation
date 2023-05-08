import numpy as np
import pandas as pd
from scipy.interpolate import interp1d
from tqdm import tqdm
from djutils import keys, merge, rowproperty, keyproperty, RestrictionError
from foundation.utils.resample import frame_index
from foundation.utility.stat import Summary
from foundation.utility.standardize import Standardize
from foundation.stimulus.video import VideoInfo
from foundation.scan.unit import UnitSet, FilteredUnits
from foundation.scan.cache import UnitsActivity
from foundation.recording.trial import Trial, TrialSet, TrialBounds, TrialVideo
from foundation.recording.trace import Trace, TraceSet, TraceTrials
from foundation.utility.resample import Rate, Offset, Resample


@keys
class ResampleVideo:
    """Resample trial video"""

    @property
    def key_list(self):
        return [
            Trial,
            Rate,
        ]

    @rowproperty
    def index(self):
        """
        Returns
        -------
        1D array
            video frame index for each of the resampled time points
        """
        # resampling flip times and period
        flips = (Trial & self.key).link.flips
        period = (Rate & self.key).link.period

        # trial and video info
        info = merge(self.key, TrialBounds, TrialVideo, VideoInfo)
        start, frames = info.fetch1("start", "frames")

        if len(flips) != frames:
            raise ValueError("Flips do not match video frames.")

        # sample index for each flip
        index = frame_index(flips - start, period)
        samples = np.arange(index[-1] + 1)

        # first flip of each sampling index
        first = np.diff(index, prepend=-1) > 0

        # for each of the samples, get the previous flip/video index
        previous = interp1d(
            x=index[first],
            y=np.where(first)[0],
            kind="previous",
        )
        return previous(samples).astype(int)


@keys
class ResampleTrace:
    """Resample trace"""

    @property
    def key_list(self):
        return [
            Trace,
            Trial,
            Rate,
            Offset,
            Resample,
        ]

    @keyproperty(Trace, Rate, Offset, Resample)
    def trials(self):
        """
        Returns
        -------
        pandas.Series (TrialSet.order)
            index -- str : trial_id (foundation.recording.trial.Trial)
            data -- 1D array : resampled trace values
        """
        # ensure trials are valid
        valid_trials = TrialSet & merge(self.key, TraceTrials)
        valid_trials = valid_trials.members

        if self.key - valid_trials:
            raise RestrictionError("Requested trials do not belong to the trace.")

        # resampling period, offset, method
        period = (Rate & self.key).link.period
        offset = (Offset & self.key).link.offset
        resample = (Resample & self.key).link.resample

        # trace resampling function
        trace = (Trace & self.key).link
        f = resample(times=trace.times, values=trace.values, target_period=period)

        # resampled trials
        trial_timing = merge(self.key, TrialBounds)
        trial_ids, starts, ends = trial_timing.fetch("trial_id", "start", "end", order_by=TrialSet.order)
        samples = [f(a, b, offset) for a, b in zip(starts, ends)]

        # pandas Series containing resampled trials
        return pd.Series(
            data=samples,
            index=pd.Index(trial_ids, name="trial_id"),
        )


def _init_resample_trace(key, connection):
    p = mp.current_process()
    p.key = key
    connection.connect()


def _resample_trace(trace):
    p = mp.current_process()
    return (ResampleTrace & trace & p.key).trials.item()


@keys
class ResampleTraces:
    """Resample trace"""

    @property
    def key_list(self):
        return [
            TraceSet & "members > 0",
            Trial,
            Rate,
            Offset,
            Resample,
        ]

    @rowproperty
    def traces(self):
        """
        Returns
        ------
        2D array -- [samples, traces (TraceSet.order)]
            resampled traces
        """
        traces = (TraceSet & self.key).ordered_keys
        key = self.key.fetch1("KEY")
        n = min(int(os.getenv("FOUNDATION_MP", 1)), mp.cpu_count(), len(traces))

        if n == 1:
            samples = ((ResampleTrace & trace & key).trials.item() for trace in traces)
            traces = list(tqdm(samples, total=len(traces), desc="Traces"))

        else:
            connection = self.key.connection
            with mp.Pool(n, _init_resample_trace, (key, connection)) as p:
                samples = p.imap(_resample_trace, traces)
                traces = list(tqdm(samples, total=len(traces), desc="Traces"))

        return np.stack(traces, 1)


@keys
class SummarizeTrace:
    """Summarize trace"""

    @property
    def key_list(self):
        return [
            Trace,
            TrialSet & "members > 0",
            Rate,
            Offset,
            Resample,
            Summary,
        ]

    @rowproperty
    def statistic(self):
        """
        Returns
        -------
        float
            trace summary statistic
        """
        # trial set
        trial_keys = (TrialSet & self.key).members

        # resampled trace
        samples = (ResampleTrace & self.key & trial_keys).trials
        samples = np.concatenate(samples)

        # summary statistic
        return (Summary & self.key).link.summary(samples)


@keys
class StandardizeTraces:
    """Trace standardization"""

    @property
    def key_list(self):
        return [
            TraceSet & "members > 0",
            TrialSet & "members > 0",
            Rate,
            Offset,
            Resample,
            Standardize,
        ]

    @rowproperty
    def transform(self):
        """
        Returns
        -------
        foundation.utility.standardize.Standardize
            trace set standardization
        """
        # trace and stat keys
        trace_keys = (TraceSet & self.key).members
        stat_keys = (Standardize & self.key).link.summary_keys

        # homogeneous mask
        hom = merge(trace_keys, TraceHomogeneous)
        hom = hom.fetch("homogeneous", order_by="trace_id ASC")
        hom = hom.astype(bool)

        # summary stats
        keys = trace_keys * self.key * stat_keys
        keys = merge(keys, TraceSummary)

        stats = dict()
        for summary_id, df in keys.fetch(format="frame").groupby("summary_id"):

            df = df.sort_values("trace_id", ascending=True)
            stats[summary_id] = df.summary.values

        # standarization transform
        return (Standardize & self.key).link.standardize(homogeneous=hom, **stats)
