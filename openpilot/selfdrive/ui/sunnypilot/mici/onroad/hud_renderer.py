"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import pyray as rl

from opendbc.car.rivian.values import RivianFlags
from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.onroad.hud_renderer import HudRenderer
from openpilot.selfdrive.ui.sunnypilot.onroad.blind_spot_indicators import BlindSpotIndicators
from openpilot.selfdrive.ui.sunnypilot.onroad.lateral_mode import lateral_mode
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, MousePos, MouseEvent

# driver icon (dmoji) placement, matches AugmentedRoadView: offset (16, 10), 60px square
DM_ICON_OFFSET_X = 16
DM_ICON_OFFSET_Y = 10
DM_ICON_SIZE = 60
DM_HOLD_PAD = 24
DM_HOLD_TIME = 1.0  # seconds held on the driver icon to toggle DM alerts for this drive
DM_OFF_RED = rl.Color(255, 60, 60, 255)


class HudRendererSP(HudRenderer):
  def __init__(self):
    super().__init__()
    self.blind_spot_indicators = BlindSpotIndicators()
    # comma 4 angle/torque tap toggle on the wheel icon (backend is device-agnostic; this is the trigger)
    self._params = Params()
    self._angle_tap_armed = False
    self._angle_tap_consumed = False

    # hold the driver icon to turn DM alerts off/on for this drive (screen only, no car controls)
    self._dm_hold_rect = rl.Rectangle(0, 0, 0, 0)
    self._dm_hold_start: float | None = None
    self._dm_hold_consumed = False
    self._txt_dm_person = gui_app.texture("icons_mici/onroad/driver_monitoring/dm_person.png", 52, 52)

  def _update_state(self) -> None:
    super()._update_state()
    self.blind_spot_indicators.update()
    lateral_mode.update()
    self.wheel_tint = lateral_mode.wheel_tint

    if self._dm_hold_start is not None:
      if not ui_state.started or not self.is_pressed:
        self._dm_hold_start = None
      elif rl.get_time() - self._dm_hold_start >= DM_HOLD_TIME:
        ui_state.toggle_dm_alerts_off()
        self._dm_hold_start = None
        self._dm_hold_consumed = True

  def _render(self, rect: rl.Rectangle) -> None:
    super()._render(rect)
    self.blind_spot_indicators.render(rect)

    self._dm_hold_rect = rl.Rectangle(rect.x, rect.y, DM_ICON_OFFSET_X + DM_ICON_SIZE + DM_HOLD_PAD,
                                      DM_ICON_OFFSET_Y + DM_ICON_SIZE + DM_HOLD_PAD)
    self._draw_dm_alerts_state(rect)

  def _draw_dm_alerts_state(self, rect: rl.Rectangle) -> None:
    center = rl.Vector2(rect.x + DM_ICON_OFFSET_X + DM_ICON_SIZE / 2, rect.y + DM_ICON_OFFSET_Y + DM_ICON_SIZE / 2)
    radius = DM_ICON_SIZE / 2

    if ui_state.dm_alerts_off:
      # red-slashed driver icon, drawn over the dmoji, for as long as alerts are off
      rl.draw_circle_v(center, radius, rl.Color(0, 0, 0, 200))
      rl.draw_texture_ex(self._txt_dm_person, rl.Vector2(center.x - self._txt_dm_person.width / 2, center.y - self._txt_dm_person.height / 2),
                         0.0, 1.0, rl.Color(255, 255, 255, 230))
      rl.draw_ring(center, radius - 4, radius, 0, 360, 36, DM_OFF_RED)
      d = (radius - 4) * 0.7071
      rl.draw_line_ex(rl.Vector2(center.x - d, center.y - d), rl.Vector2(center.x + d, center.y + d), 5, DM_OFF_RED)

    if self._dm_hold_start is not None:
      # fill a ring while holding so the driver knows the hold is registering
      progress = min((rl.get_time() - self._dm_hold_start) / DM_HOLD_TIME, 1.0)
      rl.draw_ring(center, radius + 2, radius + 8, -90, -90 + 360 * progress, 36, rl.WHITE)

  def _has_blind_spot_detected(self) -> bool:

    return self.blind_spot_indicators.detected

  def _torque_toggle_ctx(self) -> bool:
    # C4 wheel is display-only for Experimental (no shared ExpButton), so unlike the big-UI path
    # the tap is NOT gated on Experimental mode. Allow whenever: angle-harness Rivian, master
    # switch on, and MADS actively steering.
    cp = ui_state.CP
    if cp is None or cp.brand != "rivian" or not (cp.flags & RivianFlags.ANGLE_HARNESS):
      return False
    if not self._params.get_bool("RivianEnableAngleSteering"):
      return False
    sm = ui_state.sm
    return sm.recv_frame["carControl"] >= ui_state.started_frame and sm["carControl"].latActive

  def _handle_mouse_press(self, mouse_pos: MousePos) -> None:
    # arm a wheel tap only if the press lands on the wheel and the toggle is currently allowed
    self._angle_tap_armed = (self._wheel_hit_rect is not None and
                             rl.check_collision_point_rec(mouse_pos, self._wheel_hit_rect) and
                             self._torque_toggle_ctx())

    # start a DM alerts hold if the press lands on the driver icon
    self._dm_hold_consumed = False
    if ui_state.started and rl.check_collision_point_rec(mouse_pos, self._dm_hold_rect):
      self._dm_hold_start = rl.get_time()

  def _handle_mouse_event(self, mouse_event: MouseEvent) -> None:
    # sliding off the driver icon or lifting early cancels the hold
    if self._dm_hold_start is not None and (mouse_event.left_released or
                                            not rl.check_collision_point_rec(mouse_event.pos, self._dm_hold_rect)):
      self._dm_hold_start = None

  def _handle_mouse_release(self, mouse_pos: MousePos) -> None:
    # a genuine tap = press + release both on the wheel; flip the request and consume the tap so the
    # road view does not also navigate to the home screen (checked via angle_tap_consumed()).
    if self._angle_tap_armed and self._wheel_hit_rect is not None and rl.check_collision_point_rec(mouse_pos, self._wheel_hit_rect):
      self._params.put_bool("RivianForceTorqueSteerReq", not self._params.get_bool("RivianForceTorqueSteerReq"))
      self._angle_tap_consumed = True
    self._angle_tap_armed = False

  def angle_tap_consumed(self) -> bool:
    # also covers a completed driver-icon hold, so releasing it does not navigate home
    consumed = self._angle_tap_consumed or self._dm_hold_consumed
    self._angle_tap_consumed = False
    self._dm_hold_consumed = False
    return consumed
