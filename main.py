from pathlib import Path
import time

from renderer import MapRenderer

start_time = time.monotonic()
# image_data = MapRenderer(map_id="test-water").render()
image_data = MapRenderer(map_id="test-water").render(full_map=True)
Path("./output.png").write_bytes(image_data.getvalue())
print(f"Rendered in {time.monotonic() - start_time} seconds")
