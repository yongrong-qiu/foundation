import numpy as np
import pandas as pd
from scipy.interpolate import interp1d
from djutils import keys, merge, row_property, key_property, RestrictionError
from foundation.utils.resample import frame_index
from foundation.utility.stat import SummaryLink
from foundation.utility.standardize import StandardizeLink
from foundation.stimulus.video import VideoInfo
from foundation.recording.trial import TrialLink, TrialSet, TrialBounds, TrialVideo
from foundation.recording.trace import TraceLink, TraceSet, TraceTrials
from foundation.utility.resample import RateLink, OffsetLink, ResampleLink


@keys
class ResampleVideo:
    """Resample trial video"""

    @property
    def key_list(self):
        return [
            TrialLink,
            RateLink,
        ]

    @row_property
    def index(self):
        """
        Returns
        -------
        1D array
            video frame index for each of the resampled time points
        """
        # resampling flip times and period
        flips = (TrialLink & self.key).link.flips
        period = (RateLink & self.key).link.period

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
            TraceLink,
            TrialLink,
            RateLink,
            OffsetLink,
            ResampleLink,
        ]

    @key_property(TraceLink, RateLink, OffsetLink, ResampleLink)
    def samples(self):
        """
        Returns
        -------
        pd.Series
            index -- trial_id (foundation.recording.trial.TrialLink)
            data -- 1D array (resampled trace values)
        """
        # ensure trials are valid
        valid_trials = TrialSet & merge(self.key, TraceTrials)
        valid_trials = valid_trials.members

        if self.key - valid_trials:
            raise RestrictionError("Requested trials do not belong to the trace.")

        # resampling period, offset, method
        period = (RateLink & self.key).link.period
        offset = (OffsetLink & self.key).link.offset
        resample = (ResampleLink & self.key).link.resample

        # trace resampling function
        trace = (TraceLink & self.key).link
        f = resample(times=trace.times, values=trace.values, target_period=period)

        # resampled trials
        trial_timing = merge(self.key, TrialBounds)
        trial_ids, starts, ends = trial_timing.fetch("trial_id", "start", "end", order_by="start ASC")
        samples = [f(a, b, offset) for a, b in zip(starts, ends)]

        # pandas Series containing resampled trials
        return pd.Series(
            data=samples,
            index=pd.Index(trial_ids, name="trial_id"),
        )


@keys
class SummarizeTrace:
    """Summarize trace"""

    @property
    def key_list(self):
        return [
            TraceLink,
            TrialSet,
            RateLink,
            OffsetLink,
            ResampleLink,
            SummaryLink,
        ]

    @row_property
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
        samples = (ResampleTrace & self.key & trial_keys).samples
        samples = np.concatenate(samples)

        # summary statistic
        return (SummaryLink & self.key).link.summary(samples)


@keys
class StandardizeTrace:
    """Trace standardization"""

    @property
    def key_list(self):
        return [
            TraceSet,
            TrialSet,
            RateLink,
            OffsetLink,
            ResampleLink,
            StandardizeLink,
        ]

    @row_property
    def transform(self):
        """
        Returns
        -------
        foundation.utility.standardize.StandardizeLink
            trace set transformer
        """
        # trace and stat keys
        trace_keys = (TraceSet & self.key).members
        stat_keys = (StandardizeLink & self.key).link.summary_keys

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
        return (StandardizeLink & self.key).link.standardize(homogeneous=hom, **stats)
