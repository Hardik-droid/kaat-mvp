"""Candidate safety UNIT checks; synthetic timestamps are not model evidence."""
from array import array

from speech_edits import _filler_proposals


def test_only_high_probability_bounded_fillers_become_review_suggestions():
    words = [{'word': 'hello', 'start': 0., 'end': .4, 'probability': .99},
             {'word': ' um,', 'start': .5, 'end': .9, 'probability': .8},
             {'word': 'world', 'start': 1., 'end': 1.4, 'probability': .99},
             {'word': ' uh', 'start': 1.5, 'end': 1.9, 'probability': .2},
             {'word': 'मतलब', 'start': 2., 'end': 2.4, 'probability': .99}]
    cuts = _filler_proposals(words, array('h', [500]*48000), 16000, 3.)
    assert len(cuts) == 1 and cuts[0]['reason'] == 'filler_word'
    assert cuts[0]['status'] == 'suggested'
    assert cuts[0]['start'] == .52 and cuts[0]['end'] == .88


def test_silent_or_overlapping_model_tokens_never_become_speech_cuts():
    word = {'word': 'um', 'start': .2, 'end': .6, 'probability': .9}
    assert _filler_proposals([word], array('h', [0]*16000), 16000, 1.) == []
    previous = {'word': 'hello', 'start': 0., 'end': .65, 'probability': .99}
    assert _filler_proposals([previous, word], array('h', [500]*16000), 16000, 1.) == []
