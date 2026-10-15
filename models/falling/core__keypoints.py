"""COCO 17-keypoint layout (as produced by YOLOv8-pose) and small geometry helpers.

Ported from britishnew/dual_camera_fight_detector.py so the rule-based detector
behaves exactly like the fall signal there.
"""

import numpy as np

NUM_KEYPOINTS = 17

KP_NOSE = 0
KP_L_EYE, KP_R_EYE = 1, 2
KP_L_EAR, KP_R_EAR = 3, 4
KP_L_SHOULDER, KP_R_SHOULDER = 5, 6
KP_L_ELBOW, KP_R_ELBOW = 7, 8
KP_L_WRIST, KP_R_WRIST = 9, 10
KP_L_HIP, KP_R_HIP = 11, 12
KP_L_KNEE, KP_R_KNEE = 13, 14
KP_L_ANKLE, KP_R_ANKLE = 15, 16

# Index permutation that mirrors a skeleton left <-> right.
FLIP_PERM = np.array([0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15])

# Ignore keypoints the pose model isn't confident about.
KP_CONF_MIN = 0.30

# Pose connections for skeleton drawing.
SKELETON = [
    (KP_L_SHOULDER, KP_R_SHOULDER), (KP_L_SHOULDER, KP_L_HIP),
    (KP_R_SHOULDER, KP_R_HIP), (KP_L_HIP, KP_R_HIP),
    (KP_L_SHOULDER, KP_L_ELBOW), (KP_L_ELBOW, KP_L_WRIST),
    (KP_R_SHOULDER, KP_R_ELBOW), (KP_R_ELBOW, KP_R_WRIST),
    (KP_L_HIP, KP_L_KNEE), (KP_L_KNEE, KP_L_ANKLE),
    (KP_R_HIP, KP_R_KNEE), (KP_R_KNEE, KP_R_ANKLE),
    (KP_L_EYE, KP_R_EYE), (KP_L_EYE, KP_NOSE), (KP_R_EYE, KP_NOSE),
]


def kp_visible(kps_row, conf_min=KP_CONF_MIN):
    """Keypoint is usable if its confidence >= threshold."""
    return kps_row[2] >= conf_min


def spine_angle_deg(kps, conf_min=KP_CONF_MIN):
    """Angle of the spine line from vertical, in degrees (0 = upright,
    90 = flat on the ground). Returns None if either shoulder/hip is
    not confidently visible."""
    if not (kp_visible(kps[KP_L_SHOULDER], conf_min) and kp_visible(kps[KP_R_SHOULDER], conf_min)
            and kp_visible(kps[KP_L_HIP], conf_min) and kp_visible(kps[KP_R_HIP], conf_min)):
        return None
    sh_mid = (kps[KP_L_SHOULDER, :2] + kps[KP_R_SHOULDER, :2]) * 0.5
    hip_mid = (kps[KP_L_HIP, :2] + kps[KP_R_HIP, :2]) * 0.5
    dx = sh_mid[0] - hip_mid[0]
    dy = hip_mid[1] - sh_mid[1]   # flip y so "up" is positive
    if dx == 0.0 and dy == 0.0:
        return None
    return float(np.degrees(np.arctan2(abs(dx), max(abs(dy), 1e-3))))
