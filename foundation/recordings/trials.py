import numpy as np
import datajoint as dj
from djutils import link, MissingError
from foundation.stimuli import stimulus
from foundation.utils.logging import logger

pipe_stim = dj.create_virtual_module("pipe_stim", "pipeline_stimulus")
pipe_exp = dj.create_virtual_module("pipe_exp", "pipeline_experiment")
schema = dj.schema("foundation_recordings")


# ---------- Trial Link Base ----------


class TrialBase:
    @property
    def stimulus(self):
        """
        Returns
        -------
        stimulus.Stimulus
            stimulus tuple

        Raises
        ------
        MissingError
            if stimulus is missing
        """
        raise NotImplementedError()

    @property
    def flips(self):
        """
        Returns
        -------
        1D array
            stimulus flip times

        Raises
        ------
        MissingError
            if flip times are missing
        """
        raise NotImplementedError()


# ---------- Trial Link Types ----------


@schema
class ScanTrial(TrialBase, dj.Lookup):
    definition = """
    -> pipe_stim.Trial
    """

    @property
    def stimulus(self):
        trial = pipe_stim.Trial * pipe_stim.Condition & self
        stim_type = trial.fetch1("stimulus_type")
        stim_type = stim_type.split(".")[1]
        return stimulus.StimulusLink.get(stim_type, trial)

    @property
    def flips(self):
        return (pipe_stim.Trial & self).fetch1("flip_times", squeeze=True)


# ---------- Trial Link ----------


@link(schema)
class TrialLink:
    links = [ScanTrial]
    name = "trial"
    comment = "recording trial"


@schema
class Trial(dj.Computed):
    definition = """
    -> TrialLink
    ---
    -> stimulus.Stimulus
    flips                   : int unsigned      # number of stimulus flips
    """

    def make(self, key):
        link = (TrialLink & key).link

        try:
            stimulus = link.stimulus

        except MissingError:
            logger.warning(f"Missing stimulus. Skipping {key}.")
            return

        try:
            flips = link.flips

        except MissingError:
            logger.warning(f"Missing stimulus. Skipping {key}.")
            return

        key["stimulus_id"] = stimulus.fetch1("stimulus_id")
        key["flips"] = len(flips)
        self.insert1(key)


# ---------- Trials Base ----------


class TrialsBase:
    @property
    def trials(self):
        """
        Returns
        -------
        Trial
            restricted Trial table

        Raises
        ------
        MissingError
            if trials are missing
        """
        raise NotImplementedError()


# ---------- Trials Types ----------


@schema
class ScanTrials(TrialsBase, dj.Lookup):
    definition = """
    -> pipe_exp.Scan
    """

    @property
    def trials(self):
        all_trials = pipe_stim.Trial & self
        trials = Trial & (TrialLink.ScanTrial * ScanTrial & self)

        if all_trials - trials:
            raise MissingError()

        return trials


# ---------- Trials Link ----------


@link(schema)
class TrialsLink:
    links = [ScanTrials]
    name = "trials"
    comment = "recording trials"


@schema
class Trials(dj.Computed):
    definition = """
    -> TrialsLink
    ---
    trials              : int unsigned      # number of trials
    """

    class Trial(dj.Part):
        definition = """
        -> master
        -> Trial
        """

    def make(self, key):
        link = (TrialsLink & key).link

        try:
            trials = link.trials

        except MissingError:
            logger.warning(f"Mising trials. Skipping {key}.")
            return

        master_key = dict(key, trials=len(trials))
        self.insert1(master_key)

        part_keys = (self & key).proj() * trials.proj()
        self.Trial.insert(part_keys)


# ---------- Trial Restriction Base ----------


class TrialFilterBase:
    def filter(self, trials):
        """
        Parameters
        ----------
        trials : Trial
            tuples from Trial table

        Returns
        -------
        Trial
            retricted tuples from Trial table
        """
        raise NotImplementedError()


@schema
class FlipsEqualsFrames(TrialFilterBase, dj.Lookup):
    definition = """
    flips_equals_frames     : bool      # trial flips == stimulus frames
    """

    def filter(self, trials):
        key = (trials * stimulus.Stimulus * self).proj(eq="flips=frames") & "flips_equals_frames=eq"
        return trials & key
