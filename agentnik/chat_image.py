"""Chat image generation with explicit attachment handles."""
import json
from pathlib import Path
from . import image_generation
from .tools import ToolDefinition

DEFINITION = ToolDefinition('image_gen', 'request', 'Generate or edit a raster image shown to the user. request is a JSON string with prompt, optional references (array of attachment:N, previous:N, or generated:N handles), aspect_ratio, and background. Example: {"prompt":"a blue bird","references":[]}. Use references only when asked to edit or use an image. You cannot inspect the result; do not claim you saw it.', 16000)

class ChatImageTool:
    def __init__(self, config, store, messages):
        self.config, self.store = config, store
        self.secret_values = [config['connection'].get('api_key', '')]
        self.handles = {}
        if messages:
            for i, path in enumerate(messages[-1].get('images', []), 1): self.handles[f'attachment:{i}'] = path
            previous = next((m for m in reversed(messages[:-1]) if m.get('role') == 'assistant' and m.get('images')), {})
            for i, path in enumerate(previous.get('images', []), 1): self.handles[f'previous:{i}'] = path
        self.count = 0

    def instructions(self):
        handles = ', '.join(self.handles) or 'none'
        return ' Available image reference handles: ' + handles + '. Generated images receive generated:N handles. Images are shown to the user; you have not visually inspected them.'

    def prepare(self, request):
        try: value = json.loads(request)
        except (ValueError, RecursionError): raise ValueError('Image request must be a JSON object') from None
        if not isinstance(value, dict) or set(value) - {'prompt','references','aspect_ratio','background'}: raise ValueError('Invalid image request fields')
        prompt = value.get('prompt'); refs = value.get('references', [])
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt)>16000: raise ValueError('Image prompt is required')
        if not isinstance(refs, list) or len(refs)>4 or any(not isinstance(ref, str) or ref not in self.handles for ref in refs): raise ValueError('Unknown image reference; use an available handle')
        aspect = value.get('aspect_ratio', ''); background = value.get('background', '')
        if aspect not in ('','1:1','16:9','9:16','4:3','3:4','3:2','2:3') or background not in ('','transparent','opaque','auto'): raise ValueError('Invalid image options')
        data = []
        root = self.store.attachments.resolve()
        for ref in refs:
            path = Path(self.handles[ref]).resolve()
            if path.parent != root or not path.is_file() or path.stat().st_size > image_generation.MAX_IMAGE_BYTES: raise ValueError('Image reference is unavailable')
            data.append(path.read_bytes())
        return prompt, data, aspect, background

    def generate(self, prepared, cancel):
        prompt, refs, aspect, background = prepared
        return image_generation.generate(self.config['connection'], self.config['model'], prompt, refs, endpoint=self.config['endpoint'], cancel=cancel, aspect_ratio=aspect, background=background)

    def save(self, result):
        path = self.store.attach(data=result['data'], suffix=result['suffix'])
        self.count += 1
        handle = f'generated:{self.count}'
        self.handles[handle] = path
        return path, {'image':handle, 'cost':result['cost'], 'notice':'Image is shown to the user; you have not inspected it.'}
