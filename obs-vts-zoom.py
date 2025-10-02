import obspython as obs
import threading
import websocket
import json
import time
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
from enum import Enum

@dataclass
class ZoomTarget:
    factor: float
    x: float
    y: float

@dataclass
class TransformState:
    scale: Optional[obs.vec2] = None
    pos: Optional[obs.vec2] = None
    bounds: Optional[obs.vec2] = None

class ZoomState(Enum):
    IDLE = "idle"
    ZOOMING_IN = "zooming_in"
    ZOOMED = "zoomed"
    ZOOMING_OUT = "zooming_out"

class VTSZoomController:
    def __init__(self):
        self.source_name = ''
        self.vts_port = 8001
        self.clamp_to_canvas = True
        self.zoom_speed = 10  # frames at 60fps
        self.offsets = {
            'size': 20,
            'xpos': 1.0,
            'ypos': 1.0
        }
        
        self.ws = None
        self.ws_thread = None
        self.auth_token = ''
        
        self.zoom_state = ZoomState.IDLE
        self.zoom_target = ZoomTarget(1.0, 0.5, 0.5)
        self.saved_transform = TransformState()
        
        self.animation_thread = None
        self.animation_active = False
        self.current_progress = 0.0
        
    def create_request(self, msg_type: str, data: Dict[str, Any] = None) -> str:
        frame = {
            'apiName': 'VTubeStudioPublicAPI',
            'apiVersion': '1.0',
            'requestID': 'pyws',
            'messageType': msg_type
        }
        if data:
            frame['data'] = data
        obs.script_log(obs.LOG_DEBUG, f'Request: {msg_type}')
        return json.dumps(frame)
    
    def authenticate(self, ws_app, token: Optional[str] = None):
        if not token:
            ws_app.send(self.create_request('AuthenticationTokenRequest', {
                'pluginName': 'OBSxVTS Smart Zoom',
                'pluginDeveloper': 'Phenon'
            }))
        else:
            ws_app.send(self.create_request('AuthenticationRequest', {
                'pluginName': 'OBSxVTS Smart Zoom',
                'pluginDeveloper': 'Phenon',
                'authenticationToken': token
            }))
    
    def on_ws_open(self, ws_app):
        obs.script_log(obs.LOG_INFO, 'WebSocket connected to VTS')
        self.authenticate(ws_app, self.auth_token)
    
    def on_ws_message(self, ws_app, message):
        try:
            resp = json.loads(message)
            data = resp.get('data', {})
            msg_type = resp['messageType']
            
            if msg_type == 'APIError':
                obs.script_log(obs.LOG_ERROR, f'VTS API error: {data}')
            elif msg_type == 'AuthenticationTokenResponse':
                self.auth_token = data.get('authenticationToken', '')
                self.authenticate(ws_app, self.auth_token)
            elif msg_type == 'AuthenticationResponse':
                if data.get('authenticated'):
                    ws_app.send(self.create_request('EventSubscriptionRequest', {
                        'eventName': 'ModelMovedEvent',
                        'subscribe': True
                    }))
                    obs.script_log(obs.LOG_INFO, 'Authenticated with VTS')
                else:
                    self.auth_token = ''
                    obs.script_log(obs.LOG_ERROR, 'Authentication failed')
            elif msg_type == 'ModelMovedEvent':
                self.on_model_moved(data['modelPosition'])
            else:
                obs.script_log(obs.LOG_DEBUG, f'{msg_type}: {data}')
        except Exception as e:
            obs.script_log(obs.LOG_ERROR, f'Error processing message: {e}')
    
    def on_ws_close(self, ws_app, code, msg):
        obs.script_log(obs.LOG_WARNING, f'WebSocket closed: {code} - {msg}')
    
    def on_ws_error(self, ws_app, error):
        obs.script_log(obs.LOG_ERROR, f'WebSocket error: {error}')
    
    def init_websocket(self):
        try:
            self.ws = websocket.WebSocketApp(
                f'ws://localhost:{self.vts_port}',
                on_open=self.on_ws_open,
                on_message=self.on_ws_message,
                on_close=self.on_ws_close,
                on_error=self.on_ws_error
            )
            self.ws.run_forever(reconnect=5)
        except Exception as e:
            obs.script_log(obs.LOG_ERROR, f'Failed to initialize WebSocket: {e}')
    
    def on_model_moved(self, model_pos: Dict[str, float]):
        size = (model_pos['size'] + 102) / 2
        xpos = (model_pos['positionX'] + 1) / 2
        ypos = (model_pos['positionY'] - 1) / -2
        
        self.zoom_target = ZoomTarget(
            factor=self.offsets['size'] / size,
            x=self._clamp(xpos + size * self.offsets['xpos'] / 100),
            y=self._clamp(ypos + size * self.offsets['ypos'] / 100)
        )
    
    @staticmethod
    def _clamp(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
        return min(max(value, min_val), max_val)
    
    @staticmethod
    def _ease_in_out_cubic(t: float) -> float:
        if t < 0.5:
            return 4 * t ** 3
        p = 2 * t - 2
        return 1 + p ** 3 / 2
    
    def get_effective_size(self, item) -> Tuple[float, float]:
        source = obs.obs_sceneitem_get_source(item)
        if not source:
            return 0, 0
        
        sw = obs.obs_source_get_width(source)
        sh = obs.obs_source_get_height(source)
        
        scale = obs.vec2()
        bounds = obs.vec2()
        obs.obs_sceneitem_get_scale(item, scale)
        obs.obs_sceneitem_get_bounds(item, bounds)
        bbtype = obs.obs_sceneitem_get_bounds_type(item)
        
        if bbtype == obs.OBS_BOUNDS_NONE:
            return sw * scale.x, sh * scale.y
        else:
            return bounds.x, bounds.y
    
    @staticmethod
    def get_canvas_size() -> Tuple[int, int]:
        vi = obs.obs_video_info()
        if obs.obs_get_video_info(vi):
            return vi.base_width, vi.base_height
        return 1920, 1080  # fallback
    
    def calculate_zoom_transform(self, item, factor: float, target_x: float, target_y: float) -> Tuple[Optional[obs.vec2], obs.vec2, Optional[obs.vec2]]:
        pos = obs.vec2()
        scale = obs.vec2()
        bounds = obs.vec2()
        obs.obs_sceneitem_get_pos(item, pos)
        obs.obs_sceneitem_get_scale(item, scale)
        obs.obs_sceneitem_get_bounds(item, bounds)
        bbtype = obs.obs_sceneitem_get_bounds_type(item)
        
        ew, eh = self.get_effective_size(item)
        cw, ch = self.get_canvas_size()
        
        new_pos = obs.vec2()
        new_scale = None
        new_bounds = None
        
        if bbtype == obs.OBS_BOUNDS_NONE:
            # scale
            new_scale = vec2_mulf(scale, factor)
            new_pos.x = (cw / 2) - target_x * ew * new_scale.x
            new_pos.y = (ch / 2) - target_y * eh * new_scale.y
            
            if self.clamp_to_canvas:
                new_w = ew * new_scale.x
                new_h = eh * new_scale.y
                
                if new_w >= cw:
                    new_pos.x = self._clamp(new_pos.x, cw - new_w, 0)
                if new_h >= ch:
                    new_pos.y = self._clamp(new_pos.y, ch - new_h, 0)
        else:
            # bounds
            new_bounds = vec2_mulf(bounds, factor)
            new_pos.x = (cw / 2) - target_x * new_bounds.x
            new_pos.y = (ch / 2) - target_y * new_bounds.y
            
            if self.clamp_to_canvas:
                if new_bounds.x >= cw:
                    new_pos.x = self._clamp(new_pos.x, cw - new_bounds.x, 0)
                if new_bounds.y >= ch:
                    new_pos.y = self._clamp(new_pos.y, ch - new_bounds.y, 0)
        
        return new_scale, new_pos, new_bounds
    
    def animate_zoom(self):
        if not self.source_name:
            return
        
        source = obs.obs_get_source_by_name(self.source_name)
        if not source:
            return
        
        scene = obs.obs_frontend_get_current_scene()
        scene_source = obs.obs_scene_from_source(scene)
        item = obs.obs_scene_find_source(scene_source, self.source_name)
        
        if not item:
            obs.obs_source_release(source)
            obs.obs_source_release(scene)
            return
        
        start_scale = obs.vec2()
        start_pos = obs.vec2()
        start_bounds = obs.vec2()
        obs.obs_sceneitem_get_scale(item, start_scale)
        obs.obs_sceneitem_get_pos(item, start_pos)
        obs.obs_sceneitem_get_bounds(item, start_bounds)
        
        if self.zoom_state == ZoomState.ZOOMING_IN:
            end_scale, end_pos, end_bounds = self.calculate_zoom_transform(
                item, self.zoom_target.factor, self.zoom_target.x, self.zoom_target.y
            )
            if end_scale is None:
                end_scale = vec2_copy(start_scale)
            if end_bounds is None:
                end_bounds = vec2_copy(start_bounds)
        else:  
            end_scale = self.saved_transform.scale or vec2_copy(start_scale)
            end_pos = self.saved_transform.pos or vec2_copy(start_pos)
            end_bounds = self.saved_transform.bounds or vec2_copy(start_bounds)
        
        frames = max(1, self.zoom_speed)
        frame_time = 1.0 / 60.0  # 60 FPS

        for frame in range(frames):
            if not self.animation_active:
                break
            
            t = (frame + 1) / frames
            t_eased = self._ease_in_out_cubic(t)
            
            current_scale = vec2_lerp(start_scale, end_scale, t_eased)
            current_pos = vec2_lerp(start_pos, end_pos, t_eased)
            current_bounds = vec2_lerp(start_bounds, end_bounds, t_eased)
            
            obs.obs_sceneitem_set_scale(item, current_scale)
            obs.obs_sceneitem_set_pos(item, current_pos)
            obs.obs_sceneitem_set_bounds(item, current_bounds)
            
            self.current_progress = t
            time.sleep(frame_time)
        
        if self.zoom_state == ZoomState.ZOOMING_IN:
            self.zoom_state = ZoomState.ZOOMED
        elif self.zoom_state == ZoomState.ZOOMING_OUT:
            self.zoom_state = ZoomState.IDLE
        
        self.animation_active = False
        obs.obs_source_release(source)
        obs.obs_source_release(scene)
    
    def toggle_zoom(self, pressed):
        if not pressed:
            return
        if not self.source_name:
            obs.script_log(obs.LOG_WARNING, 'Warning: No zoom source set')
            return
        
        if self.animation_active:
            obs.script_log(obs.LOG_INFO, 'Animation already in progress')
            return
        
        source = obs.obs_get_source_by_name(self.source_name)
        if not source:
            obs.script_log(obs.LOG_WARNING, f'Warning: No source found with name "{self.source_name}". Name must match fully, including case.')
            return
        
        scene = obs.obs_frontend_get_current_scene()
        scene_source = obs.obs_scene_from_source(scene)
        item = obs.obs_scene_find_source(scene_source, self.source_name)
        
        if not item:
            obs.obs_source_release(source)
            obs.obs_source_release(scene)
            obs.script_log(obs.LOG_WARNING, f'Warning: Source "{self.source_name}" not in current scene')
            return
        
        if self.zoom_state in [ZoomState.IDLE, ZoomState.ZOOMING_OUT]:
            scale = obs.vec2()
            pos = obs.vec2()
            bounds = obs.vec2()
            obs.obs_sceneitem_get_scale(item, scale)
            obs.obs_sceneitem_get_pos(item, pos)
            obs.obs_sceneitem_get_bounds(item, bounds)

            self.saved_transform = TransformState(
                    vec2_copy(scale),
                    vec2_copy(pos),
                    vec2_copy(bounds)
                )
            self.zoom_state = ZoomState.ZOOMING_IN
        else:
            self.zoom_state = ZoomState.ZOOMING_OUT
        
        obs.obs_source_release(source)
        obs.obs_source_release(scene)
        
        self.animation_active = True
        self.animation_thread = threading.Thread(target=self.animate_zoom)
        self.animation_thread.daemon = True
        self.animation_thread.start()
    
    def update_settings(self, settings):
        self.source_name = obs.obs_data_get_string(settings, 'source')
        self.offsets['size'] = obs.obs_data_get_double(settings, 'offset_zoom')
        self.offsets['xpos'] = obs.obs_data_get_double(settings, 'offset_x')
        self.offsets['ypos'] = obs.obs_data_get_double(settings, 'offset_y')
        self.clamp_to_canvas = obs.obs_data_get_bool(settings, 'zoom_clamp')
        self.vts_port = obs.obs_data_get_int(settings, 'ws_port')
        self.zoom_speed = obs.obs_data_get_int(settings, 'zoom_speed')
    
    def load(self, settings):
        self.auth_token = obs.obs_data_get_string(settings, 'vts_token')
        
        self.ws_thread = threading.Thread(target=self.init_websocket, daemon=True)
        self.ws_thread.start()
        
        obs.script_log(obs.LOG_INFO, 'VTS Zoom Controller loaded')
    
    def save(self, settings):
        obs.obs_data_set_string(settings, 'vts_token', self.auth_token)
        obs.script_log(obs.LOG_INFO, 'VTS Zoom Controller saved')
    
    def unload(self):
        self.animation_active = False
        if self.animation_thread and self.animation_thread.is_alive():
            self.animation_thread.join(timeout=0.5)
        
        if self.ws:
            self.ws.close()
        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=2)
        
        obs.script_log(obs.LOG_INFO, 'VTS Zoom Controller unloaded')


controller = VTSZoomController()
zoom_hotkey_id = obs.OBS_INVALID_HOTKEY_ID

def toggle_zoom_cb(pressed):
    global controller
    if pressed:
        controller.toggle_zoom(pressed)

def vec2_copy(source: obs.vec2) -> obs.vec2:
    result = obs.vec2()
    obs.vec2_copy(result, source)
    return result

def vec2_mulf(vec: obs.vec2, scalar: float) -> obs.vec2:
    result = obs.vec2()
    obs.vec2_mulf(result, vec, scalar)
    return result

def vec2_add(a: obs.vec2, b: obs.vec2) -> obs.vec2:
    result = obs.vec2()
    obs.vec2_add(result, a, b)
    return result

def vec2_sub(a: obs.vec2, b: obs.vec2) -> obs.vec2:
    result = obs.vec2()
    obs.vec2_sub(result, a, b)
    return result

def vec2_lerp(start: obs.vec2, end: obs.vec2, t: float) -> obs.vec2:
    # start + (end - start) * t
    return vec2_add(start, vec2_mulf(vec2_sub(end, start), t))

def script_description():
    return 'Toggle zoom based on VTS model location/size.\nOn websocket errors, please make sure VTube Studio is running and API is enabled, then reload script.\n\nBy Phenon'

def script_properties():
    props = obs.obs_properties_create()
    
    p = obs.obs_properties_add_list(
        props, 'source', 'Zoom Source',
        obs.OBS_COMBO_TYPE_EDITABLE,
        obs.OBS_COMBO_FORMAT_STRING
    )
    sources = obs.obs_enum_sources()
    if sources:
        for src in sources:
            name = obs.obs_source_get_name(src)
            obs.obs_property_list_add_string(p, name, name)
        obs.source_list_release(sources)
    
    obs.obs_properties_add_int(props, 'ws_port', 'WebSocket Port', 1, 9999, 1)
    obs.obs_properties_add_int(props, 'zoom_speed', 'Zoom Speed (frames @60fps)', 1, 120, 1)
    obs.obs_properties_add_bool(props, 'zoom_clamp', 'Clamp to Canvas')
    obs.obs_properties_add_float(props, 'offset_zoom', 'Zoom Multiplier', 1.0, 1000.0, 0.01)
    obs.obs_properties_add_float(props, 'offset_x', 'Center Offset X', -1000.0, 1000.0, 0.01)
    obs.obs_properties_add_float(props, 'offset_y', 'Center Offset Y', -1000.0, 1000.0, 0.01)
    
    return props

def script_update(settings):
    global controller
    controller.update_settings(settings)

def script_load(settings):
    global controller, zoom_hotkey_id
    controller.load(settings)
    zoom_hotkey_id = obs.obs_hotkey_register_frontend(
        'toggle_vts_zoom_hotkey',
        'Toggle Zoom to Model',
        toggle_zoom_cb
    )
        
    hotkey_save_array = obs.obs_data_get_array(settings, 'toggle_vts_zoom_hotkey')
    obs.obs_hotkey_load(zoom_hotkey_id, hotkey_save_array)
    obs.obs_data_array_release(hotkey_save_array)

def script_save(settings):
    global controller, zoom_hotkey_id
    controller.save(settings)
    hotkey_save_array = obs.obs_hotkey_save(zoom_hotkey_id)
    obs.obs_data_set_array(settings, 'toggle_vts_zoom_hotkey', hotkey_save_array)
    obs.obs_data_array_release(hotkey_save_array)

def script_unload():
    global controller, zoom_hotkey_id
    controller.unload()
    obs.obs_hotkey_unregister(toggle_zoom_cb)

def script_defaults(settings):
    obs.obs_data_set_default_int(settings, 'ws_port', 8001)
    obs.obs_data_set_default_int(settings, 'zoom_speed', 25)
    obs.obs_data_set_default_bool(settings, 'zoom_clamp', True)
    obs.obs_data_set_default_double(settings, 'offset_zoom', 50)
    obs.obs_data_set_default_double(settings, 'offset_x', 0.0)
    obs.obs_data_set_default_double(settings, 'offset_y', -2.0)
