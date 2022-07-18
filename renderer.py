import itertools
import json
from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, TypedDict

import requests
from PIL import Image

IMAGE_FOLDER = Path("./img/")
DATA_FOLDER = Path("./data/")
TILE_SIZE = 40

WATER_EDGE_CANCELERS = [
    # if water tiles ("wtr") are adjacent to one of these, there will not be an edge between them
    "wtr",
    # these are from the Faerieland level
    "cld",
    "scld",
    "fc_1",
    "fc_2",
    "fc_3",
    "fc_4",
    "fc_6",
    "fc_7",
    "fc_8",
    "fc_9",
    # haven't found any other edge cases, no pun intended
]


class Map(TypedDict):
    default: str  # default tile (when within map bounds)
    border: str  # fallback tile (when outside map bounds)

    # a mapping of some arbitrary string -> tile url name. {"w": "wtr", ...} for example
    # although I use "w" for the water sprite, the "w" character could be any other single unicode character
    tiles: Dict[str, str]

    # a text representation itself, using the keys from the "tiles" mapping to represent tiles on the map
    # characters in the strings that are just a space, " " will be replaced with the default tile at render time
    layers: List[List[str]]


@dataclass
class RenderTile:
    x: int
    y: int
    z: int
    tile: str
    out_of_bounds: bool = False


class MapRenderer:
    def __init__(
        self,
        *,
        map_id: Any,
        x: int = 0,
        y: int = 0,
        visibility: int = 9,  # 9 is the default in-game
        render_water_edges: bool = True,
    ) -> None:

        self.map: Map = json.loads((DATA_FOLDER / f"{map_id}.json").read_text())

        self.rows = len(self.map["layers"][0])
        self.cols = len(self.map["layers"][0][0])

        self.visibility = visibility  # the diameter of the visible part of the map
        self.visibility |= 1  # must be odd, fix it here if it's not
        self.radius = self.visibility // 2

        self.x = x
        self.y = y

        self.render_water_edges = render_water_edges

    def get_tile(self, tile_type: str) -> Image.Image:
        """Returns an image of the tile at the given location."""

        tile = self.map["tiles"].get(tile_type)
        if tile:
            img = IMAGE_FOLDER / f"{tile}.gif"
        else:
            # for when we don't have it hardcoded
            # like for water edges
            img = IMAGE_FOLDER / f"{tile_type}.gif"

        # download it if it doesn't exist
        if not img.exists():
            img.write_bytes(
                requests.get(f"https://images.neopets.com/nq2/t/{img.name}").content
            )
        return Image.open(img)

    def get_tile_at(self, *, x: int, y: int, z: int = 0) -> RenderTile:
        """Returns a tile at the given location."""
        if x < 0 or y < 0 or x >= self.cols or y >= self.rows:
            return RenderTile(x, y, z, tile=self.map["border"], out_of_bounds=True)
        return RenderTile(
            x, y, z, tile=self.map["layers"][z][y][x], out_of_bounds=False
        )

    def get_neighbors(self, *, x: int, y: int, z: int = 0) -> List[RenderTile]:
        """Returns the neighbors of the tile at the given location in NSEW order. Only used for water edges."""
        neighbors: List[RenderTile] = [
            # add north neighbor
            self.get_tile_at(x=x, y=y - 1, z=z),
            # add south neighbor
            self.get_tile_at(x=x, y=y + 1, z=z),
            # add east neighbor
            self.get_tile_at(x=x + 1, y=y, z=z),
            # add west neighbor
            self.get_tile_at(x=x - 1, y=y, z=z),
            # add north-west neighbor
            self.get_tile_at(x=x - 1, y=y - 1, z=z),
            # add south-west neighbor
            self.get_tile_at(x=x - 1, y=y + 1, z=z),
            # add south-east neighbor
            self.get_tile_at(x=x + 1, y=y + 1, z=z),
            # add north-east neighbor
            self.get_tile_at(x=x + 1, y=y - 1, z=z),
        ]
        return neighbors

    def tile_mapper(self, *, full_map: bool = False):
        """Generates tiles for the map."""
        # we'll be adding tiles to a dictionary on a per-layer basis.
        # this allows us to have more flexibility in how we render the map
        if full_map:
            x_origin = 0
            y_origin = 0
            x_max = self.cols
            y_max = self.rows
        else:
            x_origin = -self.radius + self.x
            y_origin = -self.radius + self.y
            x_max = self.radius + self.x + 1
            y_max = self.radius + self.y + 1

        layers: DefaultDict[int, List[RenderTile]] = defaultdict(list)

        for z_index in range(len(self.map["layers"])):
            for x, y in itertools.product(
                range(x_origin, x_max), range(y_origin, y_max)
            ):
                out_of_bounds = x < 0 or y < 0 or x >= self.cols or y >= self.rows

                x_out = (x - x_origin) * TILE_SIZE
                y_out = (y - y_origin) * TILE_SIZE

                if z_index == 0 and out_of_bounds:
                    layers[z_index].append(
                        RenderTile(
                            x=x_out,
                            y=y_out,
                            z=z_index,
                            tile=self.map["border"],
                            out_of_bounds=True,
                        )
                    )
                    continue

                if out_of_bounds:
                    continue

                tile = self.map["layers"][z_index][y][x]
                if tile == " ":
                    continue

                if self.render_water_edges is False:
                    continue

                tile_name = self.map["tiles"].get(tile)
                if tile_name == "wtr":
                    # special cases for water edges below
                    # this is not particularly fast when doing a full map render, like of an overworld.
                    # when the visibility is a normal amount it's fast enough
                    # ...but overengineering it is not worth it IMO
                    neighbors = self.get_neighbors(x=x, y=y, z=z_index)
                    water_lookup = {0: "n", 1: "s", 2: "e", 3: "w"}
                    water_edges: List[str] = []
                    for index, neighbor in enumerate(neighbors[:4]):
                        if neighbor.out_of_bounds:
                            # this tile is adjacent to water, and is out of bounds, so we assume it would also be water
                            tile_name = "wtr"
                        else:
                            tile_name = (
                                self.map["tiles"].get(neighbor.tile)
                                or self.map["tiles"][self.map["default"]]
                            )
                        if tile_name not in WATER_EDGE_CANCELERS:
                            water_edges.append(water_lookup[index])

                    edges_str = "".join(water_edges)
                    if edges_str:
                        tile = f"wtr_{edges_str}"

                    # the following code is for the "caps" of water edges
                    # for example, if the tile we're currently on is water, and there's a water tile both to the east and south,
                    # then we'll put a cap where those edges meet to have a clean look, just like NQ2 does!

                    ordinal = neighbors[4:]  # NW, SW, SE, NE in that order
                    # we'll make new layers for each
                    for index, edge_letter in enumerate("acdb"):
                        if ordinal[index].out_of_bounds:
                            # this water is out of bounds, so we don't add a corner
                            continue

                        tile_name = (
                            self.map["tiles"].get(ordinal[index].tile)
                            or self.map["tiles"][self.map["default"]]
                        )

                        if tile_name not in WATER_EDGE_CANCELERS:
                            layers[len(layers) + 1].append(
                                RenderTile(
                                    x=x_out,
                                    y=y_out,
                                    z=z_index,
                                    tile=f"wtrc_{edge_letter}",
                                )
                            )

                layers[z_index].append(
                    RenderTile(x=x_out, y=y_out, z=z_index, tile=tile)
                )

        return layers

    def render(self, *, full_map: bool = False):
        """Renders the map. If full_map is True, the entire map will be rendered, otherwise it will be what's visible using the visibility + x + y attributes."""
        map_bytes = BytesIO()

        if full_map:
            image_size = (self.cols * TILE_SIZE, self.rows * TILE_SIZE)
        else:
            image_size = (self.visibility * TILE_SIZE, self.visibility * TILE_SIZE)

        base_image = Image.new("RGBA", image_size)

        # make a base layer with default background tiles
        for x, y in itertools.product(
            range(0, image_size[0], TILE_SIZE), range(0, image_size[1], TILE_SIZE)
        ):
            base_image.paste(self.get_tile(self.map["default"]), (x, y))

        tiles = self.tile_mapper(full_map=full_map)
        out_of_bounds_layer = Image.new("RGBA", image_size)
        for z_index, layer in tiles.items():
            layer_image = Image.new("RGBA", image_size)
            for tile in layer:
                if tile.out_of_bounds:
                    out_of_bounds_layer.paste(
                        self.get_tile(tile.tile), (tile.x, tile.y)
                    )
                    continue
                layer_image.paste(self.get_tile(tile.tile), (tile.x, tile.y))

            if z_index == 0:
                base_image.alpha_composite(out_of_bounds_layer)
            base_image.alpha_composite(layer_image)

        base_image.save(map_bytes, format="PNG")
        map_bytes.seek(0)
        return map_bytes
