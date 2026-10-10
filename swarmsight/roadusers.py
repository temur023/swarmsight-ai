"""Road users from a COCO detector: riders merged with their bicycle or motorcycle, duplicates removed."""
from __future__ import annotations

import numpy as np

from .detector import Detections

GROUP = {"person": "person", "bicycle": "two_wheeler", "motorcycle": "two_wheeler", "cyclist": "two_wheeler",
         "motorcyclist": "two_wheeler", "car": "vehicle", "truck": "vehicle", "bus": "vehicle"}
GROUP_IDS = {"person": 0, "two_wheeler": 1, "vehicle": 2}
VRU = {"person", "cyclist", "motorcyclist", "bicycle", "motorcycle"}
VEHICLES = {"car", "truck", "bus"}


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-9)


def compose_road_users(det: Detections, min_conf: float = 0.25) -> list[tuple[np.ndarray, str, float]]:
    """A COCO detector reports a cyclist as a person box and a bicycle box; we keep one rider object."""
    items = [(det.xyxy[i].astype(float), det.label(i), float(det.conf[i])) for i in range(len(det)) if det.conf[i] >= min_conf]
    items = [it for it in items if it[1] in GROUP]
    persons = [i for i, it in enumerate(items) if it[1] == "person"]
    bikes = [i for i, it in enumerate(items) if it[1] in ("bicycle", "motorcycle")]
    used, out = set(), []
    for b in bikes:
        bb = items[b][0]
        best, best_score = None, 0.0
        for p in persons:
            if p in used:
                continue
            pb = items[p][0]
            ix = max(0, min(pb[2], bb[2]) - max(pb[0], bb[0]))
            overlap_x = ix / max(1.0, min(pb[2] - pb[0], bb[2] - bb[0]))
            feet_in = bb[1] - 0.1 * (bb[3] - bb[1]) <= pb[3] <= bb[3] + 0.1 * (bb[3] - bb[1])
            if overlap_x > 0.5 and feet_in and pb[1] < bb[1] and overlap_x > best_score:
                best, best_score = p, overlap_x
        if best is not None:
            pb = items[best][0]
            union = np.array([min(pb[0], bb[0]), min(pb[1], bb[1]), max(pb[2], bb[2]), bb[3]])
            out.append((union, "cyclist" if items[b][1] == "bicycle" else "motorcyclist", max(items[b][2], items[best][2])))
            used.update({b, best})
    out += [it for i, it in enumerate(items) if i not in used]
    out.sort(key=lambda x: -x[2])
    keep: list[tuple[np.ndarray, str, float]] = []
    for it in out:  # one object reported as car and truck: keep the more confident box
        if not any(GROUP[k[1]] == GROUP[it[1]] and iou(k[0], it[0]) > 0.7 for k in keep):
            keep.append(it)
    return keep
