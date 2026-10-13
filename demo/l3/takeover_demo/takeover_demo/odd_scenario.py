"""The ODD as data: polygon helpers and the scenario-file reader.

No rclpy here, so the unit tests run without a ROS environment.

An OpenSCENARIO file states the ODD in its ParameterDeclarations
(docs/design/carla-island-demo.md, "ODD from the scenario"):

  IslandOddPolygon   string  "x,y;x,y;..." in metres, the Autoware map
                             frame (the frame of the file's WorldPositions)
  IslandOddMaxSpeed  double  km/h

Either may be left out; a file that declares neither is refused, because a
scenario handed to odd_monitor is there to state the ODD.
"""
import xml.etree.ElementTree as ET

POLYGON_PARAM = 'IslandOddPolygon'
SPEED_PARAM = 'IslandOddMaxSpeed'


def parse_polygon(text):
    pts = []
    for pair in filter(None, (p.strip() for p in text.split(';'))):
        x, y = (float(v) for v in pair.split(','))
        pts.append((x, y))
    if pts and len(pts) < 3:
        raise ValueError(f'segment_polygon needs >= 3 points, got {len(pts)}')
    return pts


def inside(poly, x, y):
    """Even-odd ray cast."""
    hit = False
    j = len(poly) - 1
    for i, (xi, yi) in enumerate(poly):
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def read_scenario_odd(path):
    """Return (polygon text or None, max speed km/h or None) from `path`.

    Only the top-level ParameterDeclarations are read: they are the ones a
    scenario run can override, and the ones the file states as its own.
    A value that is a parameter reference (`$name`) or an expression is
    refused rather than evaluated: the ODD must be readable as written.
    """
    root = ET.parse(path).getroot()
    decls = root.find('ParameterDeclarations')
    found = {}
    if decls is not None:
        for d in decls.findall('ParameterDeclaration'):
            name = d.get('name')
            if name in (POLYGON_PARAM, SPEED_PARAM):
                if name in found:
                    raise ValueError(f'{path}: {name} declared twice')
                value = d.get('value', '')
                if value.lstrip().startswith('$'):
                    raise ValueError(f'{path}: {name} = {value!r} is a reference; '
                                     'state the value')
                found[name] = (d.get('parameterType', ''), value)
    if not found:
        raise ValueError(f'{path}: declares neither {POLYGON_PARAM} nor {SPEED_PARAM}')
    poly = speed = None
    if POLYGON_PARAM in found:
        ptype, poly = found[POLYGON_PARAM]
        if ptype != 'string':
            raise ValueError(f'{path}: {POLYGON_PARAM} must be parameterType="string"')
        if len(parse_polygon(poly)) < 3:
            raise ValueError(f'{path}: {POLYGON_PARAM} is empty')
    if SPEED_PARAM in found:
        ptype, text = found[SPEED_PARAM]
        if ptype != 'double':
            raise ValueError(f'{path}: {SPEED_PARAM} must be parameterType="double"')
        speed = float(text)
        if not speed > 0.0:
            raise ValueError(f'{path}: {SPEED_PARAM} must be > 0 km/h')
    return poly, speed
