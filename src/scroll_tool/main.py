import ctypes
from ctypes import c_ubyte
from ctypes.wintypes import COLORREF, DWORD, HWND, HDC, POINT, SIZE
import win32con
import win32gui
import wx
import time
import numpy as np
from enum import Enum, auto
import sys

TWO_PI = np.pi*2

class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", c_ubyte),
        ("BlendFlags", c_ubyte),
        ("SourceConstantAlpha", c_ubyte),
        ("AlphaFormat", c_ubyte),
    ]

def get_mouse_position_in_window(hwnd):
    # Get the global mouse cursor position
    pt = win32gui.GetCursorPos()

    # Convert screen coordinates to the window's client area coordinates
    pt = win32gui.ScreenToClient(hwnd, pt)
    
    return pt

class ScrollToolInteractionType(Enum):
    SCROLL_WHEEL = auto()
    CLOSE_BUTTON = auto()

def lerp(a,b,t):
    return a+(b-a)*t

def inv_lerp(a,b,v):
    return (v-a)/(b-a)

def ease_circ(x):
    return np.sqrt(1-np.pow(1-x,2))

def angle_unwrap(a):
    return a-TWO_PI*(a//TWO_PI)

class ScrollToolFrame(wx.Frame):
    def __init__(
        self,
        start_pos: tuple[int, int],
        active_window_hwnd: int,
        scroll_pos: tuple[int,int],
        parent=None,

        size: tuple[int, int] = (500, 500),
        radius: int = 400, # Total radius of the scroll visuals
        border_thickness_fac: float = 0.05, # Width of ring border as a percentage of total ring thickness

        hole_fac: float = 0.75, # Percentage of total radius that the center hole should take up

        n_divisions: int = 20, # How many segments the ring should be divided up in

        selector_size_fac: float = 0.05, # Angular range the selector should fill up
        selector_margin_fac: float = 0.1, # Percentage of ring radius that should be subtracted from the selector as a margin

        selector_rounded_corners: bool = True, # Wether or not the selector should have rounded corners
        selector_rounding_fac_h: float = 0.2, # Total horizontal space taken up by rounded corners
        selector_rounding_fac_v: float = 0.2, # Total vertical space taken up by rounded corners

        close_button_radius_fac: float = 0.5, # Percentage of hole radius that the close button should take up

        dead_zone_radius_fac: float = 0.5, # The radius of the center dead-zone as a percentage of the hole radius
    ):
        wx.Frame.__init__(
            self,
            parent,
            size=size,
            style=wx.STAY_ON_TOP
        )

        hwnd = self.GetHandle()
        self.hwnd = hwnd

        extended_style_settings = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        window_long = extended_style_settings | win32con.WS_EX_LAYERED
        self.window_long = window_long

        win32gui.SetWindowLong(
            hwnd,
            win32con.GWL_EXSTYLE,
            window_long
        )
        self.blend_func = BLENDFUNCTION(win32con.AC_SRC_OVER, 0, 255, win32con.AC_SRC_ALPHA)

        self.SetTitle("Scroll tool")
        self.Center()

        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_click_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_click_up)
        self.Bind(wx.EVT_MOTION, self.on_motion)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self.on_mouse_capture_lost)

        self.size = size
        self.width = size[0]
        self.height = size[1]
        self.timer = wx.Timer(self)
        self.timer.Start(2)
        self.start_time = time.time_ns()
        self.time = time.time_ns()

        self.active_window_hwnd = active_window_hwnd
        self.scroll_pos = scroll_pos

        self.start_pos = start_pos

        self.total_radius = radius
        self.hole_fac = hole_fac
        hole_radius = (radius*hole_fac)
        self.hole_radius = hole_radius
        ring_thickness = radius-hole_radius
        self.ring_thickness = ring_thickness
        selector_margin = ring_thickness*selector_margin_fac
        self.selector_edge_v_inner = hole_radius+selector_margin
        self.selector_edge_v_outer = radius-selector_margin
        self.selector_thickness = self.selector_edge_v_outer-self.selector_edge_v_inner
        self.selector_rounded_corners = selector_rounded_corners
        self.selector_rounding_fac_v = selector_rounding_fac_h
        self.selector_rounding_fac_h = selector_rounding_fac_v
        self.nudge_angle = TWO_PI/n_divisions
        self.selector_size = TWO_PI*selector_size_fac
        close_button_radius = hole_radius*close_button_radius_fac
        self.close_button_radius = close_button_radius
        dead_zone_radius = hole_radius*dead_zone_radius_fac
        self.dead_zone_radius = dead_zone_radius

        w,h = self.size

        aa_edge_size = 0.5
        border_size = ring_thickness*border_thickness_fac

        pixel_coords = np.mgrid[-w/2:w/2,-h/2:h/2]
        angles = np.atan2(pixel_coords[0],pixel_coords[1])+np.pi
        distances = np.sqrt(pixel_coords[0]**2+pixel_coords[1]**2)
        ring_mask = (distances < self.total_radius)*(distances > self.hole_radius)
        ring_aa_mask = ring_mask^(distances < (radius-aa_edge_size))*(distances > (hole_radius+aa_edge_size))
        ring_border_mask = ring_mask^(distances < (radius-border_size))*(distances > (hole_radius+border_size))
        hole_mask = (distances < self.hole_radius)
        close_button_mask = (distances < self.close_button_radius)
        close_button_aa_mask = close_button_mask^(distances < (close_button_radius-aa_edge_size))

        self.angles = angles
        self.distances = distances
        self.ring_mask = ring_mask
        self.ring_border_mask = ring_border_mask
        self.ring_aa_mask = ring_aa_mask
        self.hole_mask = hole_mask
        self.close_button_mask = close_button_mask
        self.close_button_aa_mask = close_button_aa_mask

        self.border_color = np.array((16, 16, 20))
        bg_colors = ((26, 27, 38),(22, 22, 30))
        self.bg_colors = [np.array(c) for c in bg_colors]
        self.selector_color = np.array((100,100,200))
        self.close_button_color = np.array((52, 54, 76))

        self.current_interaction_type = None
        self.awaiting_left_up = False
        self.last_click_pos = None
        self.drag_angle = None
        self.prev_drag_angle = None
        self.prev_drag_pos = None
        self.total_windings = 0
        self.hovering_over_close_btn = False

    def on_click_down(self, event):
        x, y = get_mouse_position_in_window(self.hwnd)
        x-=self.width/2
        y-=self.height/2

        event_processed = False
        if self.total_radius > np.sqrt(x**2+y**2) > self.hole_radius:
            self.drag_angle = np.atan2(y,x)+np.pi
            self.prev_drag_angle = self.drag_angle
            self.prev_drag_pos = (x,y)
            self.current_interaction_type = ScrollToolInteractionType.SCROLL_WHEEL
            win32gui.SetWindowLong(self.hwnd,win32con.GWL_EXSTYLE, self.window_long|win32con.WS_EX_TRANSPARENT)
            event_processed = True

        elif np.sqrt(x**2+y**2) < self.close_button_radius:
            self.current_interaction_type = ScrollToolInteractionType.CLOSE_BUTTON
            event_processed = True
            
        if event_processed:
            self.awaiting_left_up = True
            wx.Window.CaptureMouse(self)

    def on_click_up(self, event):
        if not self.awaiting_left_up:
            return

        if self.hovering_over_close_btn:
            wx.Window.ReleaseMouse(self)
            self.Refresh(True)
            sys.exit(0)

        win32gui.SetWindowLong(self.hwnd,win32con.GWL_EXSTYLE, self.window_long)
        self.awaiting_left_up = False
        wx.Window.ReleaseMouse(self)
        self.Refresh(True)

    def on_motion(self,event):
        x,y = event.GetPosition()
        x-=self.width/2
        y-=self.height/2

        hovering = np.sqrt(x**2+y**2) < self.close_button_radius
        if hovering != self.hovering_over_close_btn:
            self.hovering_over_close_btn = hovering
            self.Refresh(True)

        if not self.awaiting_left_up:
            return

        if self.current_interaction_type == ScrollToolInteractionType.SCROLL_WHEEL and np.sqrt(x**2+y**2) > self.dead_zone_radius:
            angle = np.atan2(y,x)+np.pi
            
            prev_x,prev_y = self.prev_drag_pos
            if np.sqrt(prev_x**2+prev_y**2) < self.dead_zone_radius:
                self.prev_drag_angle = angle

            if self.prev_drag_angle-angle > 1*np.pi:
                self.drag_angle = angle+(angle-self.prev_drag_angle)
                self.send_scroll_wheel_nudge(-1)
            elif self.prev_drag_angle-angle < 1*-np.pi:
                self.drag_angle = angle+(angle-self.prev_drag_angle)
                self.send_scroll_wheel_nudge(1)
            else:
                segment = angle//self.nudge_angle
                last_segment = self.prev_drag_angle//self.nudge_angle
                if segment-last_segment != 0:
                    self.send_scroll_wheel_nudge(-np.sign(segment-last_segment))

            self.drag_angle = angle
            self.prev_drag_angle = angle
            self.prev_drag_pos = (x,y)
            self.Refresh(True)

    def on_mouse_capture_lost(self,event):
        win32gui.SetWindowLong(self.hwnd,win32con.GWL_EXSTYLE, self.window_long)
        self.awaiting_left_up = False
        self.Refresh(True)

    def send_scroll_wheel_nudge(self,nudges):
        delta = win32con.WHEEL_DELTA * int(nudges)
        w_param = (delta << 16)

        x,y = self.scroll_pos
        l_param =(y << 16) | (x & 0xFFFF)


        win32gui.PostMessage(self.active_window_hwnd, win32con.WM_MOUSEWHEEL, w_param, l_param)

    def layered_update(self, dc, blend_func):
        px, py = self.start_pos
        w,h = self.size
        px -= w//2
        py -= h//2

        scrdc = wx.ScreenDC().GetHandle()
        hwnd = self.GetHandle()
        res = ctypes.windll.user32.UpdateLayeredWindow(
            HWND(hwnd),  # [in]           HWND          hWnd,
            HDC(scrdc),  # [in, optional] HDC           hdcDst,
            ctypes.pointer(POINT(px, py)),  # [in, optional] POINT         *pptDst,
            ctypes.pointer(SIZE(w,h)),  # [in, optional] SIZE          *psize,
            HDC(dc.GetHandle()),  # [in, optional] HDC           hdcSrc,
            ctypes.pointer(POINT(0, 0)),  # [in, optional] POINT         *pptSrc,
            COLORREF(0),  # [in]           COLORREF      crKey,
            ctypes.pointer(blend_func),  # [in, optional] BLENDFUNCTION *pblend,
            DWORD(win32con.ULW_ALPHA),  # [in]           DWORD         dwFlags
        )
        if res == 0:
            print(ctypes.windll.kernel32.GetLastError())

    def on_paint(self, event):
        w,h = self.size
        self.time = time.time_ns() - self.start_time

        angles = self.angles 
        distances = self.distances
        ring_mask = self.ring_mask
        ring_border_mask = self.ring_border_mask
        ring_aa_mask = self.ring_aa_mask
        hole_mask = self.hole_mask
        close_button_mask = self.close_button_mask
        close_button_aa_mask = self.close_button_aa_mask

        border_color = self.border_color
        bg_colors = self.bg_colors
        selector_color = self.selector_color
        close_button_color = self.close_button_color

        cdata = np.zeros((h,w,3))[:,:]+bg_colors[0]
        cdata[angles/self.nudge_angle%2<1] = bg_colors[1]
        cdata[close_button_mask] = close_button_color
        cdata[ring_border_mask] = border_color

        adata = np.zeros((h,w))
        adata[ring_mask] = 255 
        adata[hole_mask] = 1
        adata[close_button_mask] = 100 if self.hovering_over_close_btn else 50
        adata[ring_aa_mask|close_button_aa_mask]*=0.75

        if self.awaiting_left_up:
            match(self.current_interaction_type):
                case ScrollToolInteractionType.SCROLL_WHEEL:
                    selector_angles = angle_unwrap(angles - self.drag_angle+self.selector_size/2)

                    selector_mask = (
                        (selector_angles >= 0) & (selector_angles <= self.selector_size)
                        & (distances >= self.selector_edge_v_inner)
                        & (distances <= self.selector_edge_v_outer)
                    )

                    if self.selector_rounded_corners:
                        scaled_angles = selector_angles/self.selector_size
                        scaled_distance = inv_lerp(self.selector_edge_v_inner, self.selector_edge_v_outer, distances)

                        rounding_h_mask = (
                            (scaled_angles >= 0) & (scaled_angles <= 1)
                            & (scaled_distance >= self.selector_rounding_fac_v) & (scaled_distance <= 1-self.selector_rounding_fac_v)
                        )
                        rounding_v_mask = (
                                (scaled_angles >= self.selector_rounding_fac_h/2) & (scaled_angles <= 1-self.selector_rounding_fac_h/2)
                                & (scaled_distance >= 0) & (scaled_distance <= 1)
                            )

                        corners_mask = (~rounding_h_mask & ~rounding_v_mask) & selector_mask

                        inner_corners = corners_mask & (scaled_distance <= 0.5)
                        outer_corners = corners_mask & (scaled_distance >= 0.5)

                        corner_i_a = inner_corners & (scaled_angles <= 0.5) 
                        corner_i_b = inner_corners & (scaled_angles >= 0.5)
                        corner_o_a = outer_corners & (scaled_angles <= 0.5)
                        corner_o_b = outer_corners & (scaled_angles >= 0.5)

                        rounded_corner_i_a = corner_i_a & (scaled_distance >= lerp(0,self.selector_rounding_fac_v, 1-ease_circ(inv_lerp(0,self.selector_rounding_fac_h/2,scaled_angles))))
                        rounded_corner_i_b = corner_i_b & (scaled_distance >= lerp(0,self.selector_rounding_fac_v, 1-ease_circ(inv_lerp(1,1-self.selector_rounding_fac_h/2,scaled_angles))))
                        rounded_corner_o_a = corner_o_a & (scaled_distance <= lerp(1-self.selector_rounding_fac_v,1, ease_circ(inv_lerp(0,self.selector_rounding_fac_h/2,scaled_angles))))
                        rounded_corner_o_b = corner_o_b & (scaled_distance <= lerp(1-self.selector_rounding_fac_v,1, ease_circ(inv_lerp(1,1-self.selector_rounding_fac_h/2,scaled_angles))))

                        selector_mask = (selector_mask & ~corners_mask)
                        selector_mask[corner_i_a] |= rounded_corner_i_a[corner_i_a]
                        selector_mask[corner_i_b] |= rounded_corner_i_b[corner_i_b]
                        selector_mask[corner_o_a] |= rounded_corner_o_a[corner_o_a]
                        selector_mask[corner_o_b] |= rounded_corner_o_b[corner_o_b]

                    selector_mask = np.repeat(selector_mask[:, :, np.newaxis], 3, axis=2)
                    cdata = np.where(selector_mask,selector_color,cdata)
                case ScrollToolInteractionType.SCROLL_WHEEL:
                    cdata[close_button_mask] = bg_colors[1]

        img = wx.Image(
            width=w, height=h, data=cdata.astype(np.uint8), alpha=adata.astype(np.uint8)
        )
        bmp = img.ConvertToBitmap()
        memdc = wx.MemoryDC(bmp)
        self.layered_update(memdc, self.blend_func)

def show_frame(size,radius,hole_fac):
    cursor_pos = win32gui.GetCursorPos()
    active_window_hwnd = win32gui.WindowFromPoint(cursor_pos)

    scroll_pos = get_mouse_position_in_window(active_window_hwnd)

    app = wx.App()
    frame = ScrollToolFrame(
        start_pos = cursor_pos,
        active_window_hwnd = active_window_hwnd,
        scroll_pos= scroll_pos,
        size=size,
        radius = radius,
        hole_fac = hole_fac,
    )
    frame.Show(True)
    frame.Refresh(True)
    app.MainLoop()

if __name__ == "__main__":
    show_frame((500,500),150,0.75)