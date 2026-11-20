"""Check collision footprints and following gaps on sampled roadway paths."""
import numpy as np


def footprint_gaps(first, second):
    """Return separating-axis and same-lane following gaps in metres.

    Each input is (positions, unit headings, width, length) with matched
    samples. A negative separating-axis gap means an overlap.
    """
    p, a, w1, l1 = first
    q, b, w2, l2 = second
    left = np.stack((-a[:, 1], a[:, 0]), axis=1)
    right = np.stack((-b[:, 1], b[:, 0]), axis=1)
    delta = q-p

    def dot(u, v):
        return np.einsum("ij,ij->i", u, v)

    def gap(axis):
        return abs(dot(delta, axis)) - (
            l1*abs(dot(a,axis)) + l2*abs(dot(b,axis))
            + w1*abs(dot(left,axis)) + w2*abs(dot(right,axis))
        )/2

    lateral = abs(dot(delta, left))
    longitudinal = gap(a)
    following = np.where((dot(a,b)>.95)&(lateral<1.15),longitudinal,np.nan)
    return np.maximum.reduce([longitudinal,gap(left),gap(b),gap(right)]), following
