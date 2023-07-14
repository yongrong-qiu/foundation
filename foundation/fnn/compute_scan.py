from djutils import keys, merge, rowproperty
from foundation.virtual import utility, stimulus, scan, recording, fnn


@keys
class VisualScanModel:
    """Visual Scan CC Norm"""

    @property
    def keys(self):
        return [
            (scan.Scan * fnn.NetworkModel) & (fnn.Network.VisualNetwork * fnn.Data.VisualScan),
        ]

    @property
    def data(self):
        return self.key * fnn.Network.VisualNetwork.proj("data_id")

    @property
    def rate(self):
        key = self.data * fnn.Data.VisualScan * fnn.Spec.VisualSpec
        return key.proj("rate_id")

    @property
    def unit_resample(self):
        key = self.data * fnn.Data.VisualScan * fnn.Spec.VisualSpec
        return key.proj(resample_id="unit_resample_id")

    @property
    def unit_offset(self):
        key = self.data * fnn.Data.VisualScan * fnn.Spec.VisualSpec
        return key.proj(offset_id="unit_offset_id")

    @property
    def unit_standardize(self):
        key = self.data * fnn.Data.VisualScan * fnn.Spec.VisualSpec
        return key.proj(standardize_id="unit_standardize_id")

    @property
    def unit_traces(self):
        key = (
            self.data
            * fnn.Data.VisualScan
            * recording.ScanUnits
            * recording.TraceSet.Member
            * recording.Trace.ScanUnit
            * recording.ScanUnit
        )
        return key.proj("traceset_index")

    @property
    def standardize_trials(self):
        key = self.data * fnn.Data.VisualScan * recording.ScanTrials
        return key.proj("trialset_id")


@keys
class VisualScanPerformance:
    """Visual Scan CC Norm"""

    @property
    def keys(self):
        return [
            VisualScanModel.key_source,
            utility.Bool.proj(trial_perspective="bool"),
            utility.Bool.proj(trial_modulation="bool"),
            recording.TrialFilterSet,
            stimulus.VideoSet,
            utility.Burnin,
        ]

    @property
    def cc_norm(self):
        # key
        key = self.key.fetch(as_dict=True)

        # unit keys
        rate = (VisualScanModel & key).rate
        resample = (VisualScanModel & key).unit_resample
        offset = (VisualScanModel & key).unit_offset
        traces = (VisualScanModel & key).unit_traces

        # CC max
        cc_max = recording.VisualMeasure & utility.Measure.CCMax.fetch1("KEY")
        cc_max = (cc_max * self.key * rate * resample * offset * traces).proj("traceset_index", cc_max="measure")

        # CC abs
        cc_abs = fnn.VisualUnitCorrelation & utility.Correlation.CCSignal.fetch1("KEY")
        cc_abs = (cc_abs * self.key).proj(traceset_index="unit_index", cc_abs="correlation")

        # CC norm
        return (cc_abs * cc_max).proj("cc_abs", "cc_max", cc_norm="cc_abs / cc_max")
