"""
Tests for VelocityProfiler — especially the WP-switch continuity (no cruise spike).

Root-cause of the bug (fixed here):
  PathFollower switches wp_index when dist_to_next < wp_next['radius'].
  At that instant, dist_from_prev ≈ dist_to_next ≤ radius.

  Old code: d_accel = max(kinematic, radius), so at switch:
      alpha = dist_from_prev / d_accel = radius / radius = 1.0
      tau_acc = tau_cruise   ← spike to cruise!

  Fixed code: dist_past_wp = max(0, dist_from_prev - radius), so at switch:
      dist_past_wp = max(0, radius - radius) = 0
      alpha = 0 / d_accel = 0
      tau_acc = tau_wp       ← no spike
"""

import pytest
from src.gnc.autopilot import VelocityProfiler

# ── Helpers ───────────────────────────────────────────────────────────────────

RADIUS = 5.0
TAU_CRUISE = 68.0   # ≈ 2 kn with Salpa 1 drag model
ACCEL = 0.3         # m/s²


def make_profiler_and_wps(tau_cruise=TAU_CRUISE, accel=ACCEL, wp1_speed=0.0):
    """
    3-WP route: WP0 (bridge, no speed constraint) → WP1 (target speed) → WP2 (stop).
    Returns (profiler, wps).
    """
    profiler = VelocityProfiler(tau_x_cruise=tau_cruise, accel_ms2=accel)
    wps = [
        {'N':   0.0, 'E': 0.0, 'radius': RADIUS, 'speed': None},      # bridge WP
        {'N': 100.0, 'E': 0.0, 'radius': RADIUS, 'speed': wp1_speed},  # WP1
        {'N': 200.0, 'E': 0.0, 'radius': RADIUS, 'speed': 0.0},        # stop WP
    ]
    profiler.set_waypoints(wps)
    return profiler, wps


# ── Test 1: No cruise spike at WP switch (stop WP) ───────────────────────────

def test_no_cruise_spike_at_stop_wp_switch():
    """
    At the switch instant for a stop WP:
      - dist_from_prev = radius  (vehicle just entered acceptance circle)
      - tau_x must NOT be at or near cruise
    """
    profiler, _ = make_profiler_and_wps(wp1_speed=0.0)
    cruise = profiler.tau_x_cruise

    # Just BEFORE switch: wp_idx=0, vehicle at the acceptance boundary of WP1
    tau_before = profiler.get_tau_x(
        wp_idx=0,
        dist_to_next=RADIUS,   # at the acceptance circle edge
        dist_from_prev=95.0,   # far from WP0
    )

    # Just AFTER switch: wp_idx=1, same physical position
    tau_at_switch = profiler.get_tau_x(
        wp_idx=1,
        dist_to_next=100.0,    # far from WP2
        dist_from_prev=RADIUS, # 5 m from WP1 — same distance that triggered the switch
    )

    # Main assertion: tau must NOT spike to cruise
    assert tau_at_switch < cruise * 0.5, (
        f"Cruise spike at stop-WP switch: tau={tau_at_switch:.1f} N  "
        f"(cruise={cruise:.1f} N, ratio={tau_at_switch / cruise:.2f}). "
        f"Expected tau_at_switch < {cruise * 0.5:.1f} N."
    )

    # Secondary: tau must not jump UP relative to what it was before the switch
    assert tau_at_switch <= tau_before + 5.0, (
        f"tau jumped at switch: before={tau_before:.1f} N → at_switch={tau_at_switch:.1f} N"
    )


# ── Test 2: No cruise spike for a passing WP ─────────────────────────────────

def test_no_cruise_spike_at_passing_wp_switch():
    """Same check for a passing WP (speed = 1.0 kn), where the kinematic accel
    ramp is shorter than the acceptance radius."""
    profiler, _ = make_profiler_and_wps(wp1_speed=1.0)
    cruise = profiler.tau_x_cruise

    tau_wp1 = profiler._wp_tau[1]  # equilibrium tau at 1.0 kn

    tau_at_switch = profiler.get_tau_x(
        wp_idx=1,
        dist_to_next=100.0,
        dist_from_prev=RADIUS,
    )

    # Must not spike to cruise; should be ≤ tau_wp1 (the WP's equilibrium)
    assert tau_at_switch < cruise * 0.9, (
        f"Cruise spike at passing-WP switch: tau={tau_at_switch:.1f} N "
        f"(cruise={cruise:.1f} N)"
    )
    assert tau_at_switch <= tau_wp1 + 1.0, (
        f"tau > tau_wp1 at switch: tau_at_switch={tau_at_switch:.1f}, tau_wp1={tau_wp1:.1f}"
    )


# ── Test 3: Accel ramp is active outside the acceptance circle ────────────────

def test_accel_ramp_active_outside_circle():
    """
    After the vehicle exits the acceptance circle (dist_from_prev > radius),
    the accel ramp must smoothly increase tau from tau_wp toward cruise.
    """
    profiler, _ = make_profiler_and_wps(wp1_speed=0.0)
    cruise = profiler.tau_x_cruise

    d_accel = profiler._accel_dist[1]  # kinematic ramp distance for WP1

    # Sample tau at several distances past the acceptance circle (sorted ascending)
    prev_tau = profiler.get_tau_x(
        wp_idx=1, dist_to_next=200.0, dist_from_prev=RADIUS
    )
    extras = sorted([0.5 * d_accel, d_accel, 1.5 * d_accel, 2.0 * d_accel])
    for extra in extras:
        tau = profiler.get_tau_x(
            wp_idx=1,
            dist_to_next=200.0,
            dist_from_prev=RADIUS + extra,
        )
        assert tau >= prev_tau - 1e-6, (
            f"Accel ramp must be non-decreasing: tau({RADIUS + extra:.1f}m)={tau:.1f} N "
            f"< tau({RADIUS + extra - 0.5:.1f}m)={prev_tau:.1f} N"
        )
        prev_tau = tau

    # At the end of the ramp (radius + d_accel), tau should be at cruise
    tau_end = profiler.get_tau_x(
        wp_idx=1,
        dist_to_next=200.0,
        dist_from_prev=RADIUS + d_accel,
    )
    assert abs(tau_end - cruise) < 1.0, (
        f"At end of accel ramp, tau should be cruise: {tau_end:.1f} vs {cruise:.1f} N"
    )


# ── Test 4: Tau is at tau_wp inside the acceptance circle ────────────────────

def test_tau_is_wp_speed_inside_circle():
    """
    While inside the acceptance circle (dist_from_prev < radius), the accel
    zone gives tau_wp (alpha=0), so tau_x ≤ tau_wp (no premature thrust increase).
    """
    profiler, _ = make_profiler_and_wps(wp1_speed=0.0)
    tau_wp1 = profiler._wp_tau[1]  # = 0 for stop WP

    for d in [0.5, 1.0, 2.0, 3.0, 4.0]:
        tau = profiler.get_tau_x(
            wp_idx=1,
            dist_to_next=200.0,
            dist_from_prev=d,  # inside circle
        )
        assert tau <= tau_wp1 + 1.0, (
            f"Inside acceptance circle (dist={d}m), tau={tau:.1f} N > tau_wp1={tau_wp1:.1f} N"
        )


# ── Test 5: Decel zone still works correctly ──────────────────────────────────

def test_decel_zone_not_broken():
    """
    The existing decel zone must still work: approaching the next WP, tau
    should decrease from cruise toward tau_wp of that WP.
    """
    profiler, _ = make_profiler_and_wps(wp1_speed=0.0)
    d_decel = profiler._ramp_dist[2]  # decel ramp distance for WP2 (stop WP)
    cruise = profiler.tau_x_cruise

    # Far from WP2: tau = cruise
    tau_far = profiler.get_tau_x(
        wp_idx=1,
        dist_to_next=d_decel * 2,
        dist_from_prev=RADIUS + d_decel * 2,
    )
    assert abs(tau_far - cruise) < 1.0, f"Far from WP2: expected cruise, got {tau_far:.1f} N"

    # At the start of the decel ramp: tau starts decreasing
    tau_ramp_start = profiler.get_tau_x(
        wp_idx=1,
        dist_to_next=d_decel,
        dist_from_prev=RADIUS + d_decel,
    )
    assert tau_ramp_start <= cruise, (
        f"At decel ramp start, tau={tau_ramp_start:.1f} N should be ≤ cruise={cruise:.1f} N"
    )

    # Midway through the decel ramp: tau is between cruise and 0
    tau_mid = profiler.get_tau_x(
        wp_idx=1,
        dist_to_next=d_decel / 2,
        dist_from_prev=RADIUS + d_decel + d_decel / 2,
    )
    assert 0 <= tau_mid < cruise, f"Mid-decel tau={tau_mid:.1f} N out of range [0, {cruise:.1f}]"
    assert tau_mid < tau_ramp_start + 1.0, (
        f"Decel zone not monotone: mid={tau_mid:.1f} > ramp_start={tau_ramp_start:.1f}"
    )
