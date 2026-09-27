"""Digital clone of a 1.5 mL microfuge tube, revolved from the labware catalog profile.
Not a part to print — a thing to drop into racks and holders to check fit. Profile is ESTIMATED until measured.
"""
from build123d import *
from labware import clone

P = dict(item="tube_1_5ml")
RANGES = {}

def build(P):
    return clone(P["item"])
