"""odd_scenario: the ODD read from an OpenSCENARIO file.

Run: python3 -m pytest demo/l3/takeover_demo/test (no ROS environment needed).
"""
import pathlib
import sys

import pytest

PKG = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

from takeover_demo.odd_scenario import (  # noqa: E402
    inside, parse_polygon, read_scenario_odd)

REPO = PKG.parents[2]
ODD_XOSC = REPO / 'demo/carla/scenarios/town01_island_odd.xosc'


def xosc(tmp_path, decls):
    p = tmp_path / 's.xosc'
    p.write_text('<?xml version="1.0"?><OpenSCENARIO><ParameterDeclarations>'
                 + decls + '</ParameterDeclarations></OpenSCENARIO>')
    return p


def test_the_demo_scenario_declares_the_odd():
    poly, kmh = read_scenario_odd(ODD_XOSC)
    pts = parse_polygon(poly)
    assert kmh == 30.0
    assert len(pts) == 4
    # the start pose and the lane centre east of the boundary are inside ...
    assert inside(pts, 315.0, -130.3)
    assert inside(pts, 241.0, -130.3)
    # ... the lane west of the boundary (where the ego goes) is not
    assert not inside(pts, 239.0, -130.3)
    assert not inside(pts, 110.0, -130.3)
    # and the EKF's lateral noise (0.95 m median) does not leave it
    assert inside(pts, 300.0, -130.3 - 1.9)
    assert inside(pts, 300.0, -130.3 + 1.9)


def test_one_parameter_is_enough(tmp_path):
    p = xosc(tmp_path, '<ParameterDeclaration name="IslandOddMaxSpeed" '
                       'parameterType="double" value="25"/>')
    assert read_scenario_odd(p) == (None, 25.0)


def test_other_parameters_are_ignored(tmp_path):
    p = xosc(tmp_path,
             '<ParameterDeclaration name="Other" parameterType="string" value="x"/>'
             '<ParameterDeclaration name="IslandOddPolygon" parameterType="string" '
             'value="0,0;1,0;1,1"/>')
    assert read_scenario_odd(p) == ('0,0;1,0;1,1', None)


@pytest.mark.parametrize('decls, msg', [
    ('', 'declares neither'),
    ('<ParameterDeclaration name="IslandOddMaxSpeed" parameterType="double" value="$v"/>',
     'reference'),
    ('<ParameterDeclaration name="IslandOddMaxSpeed" parameterType="string" value="30"/>',
     'double'),
    ('<ParameterDeclaration name="IslandOddMaxSpeed" parameterType="double" value="0"/>',
     '> 0'),
    ('<ParameterDeclaration name="IslandOddPolygon" parameterType="string" value="0,0;1,1"/>',
     '>= 3 points'),
    ('<ParameterDeclaration name="IslandOddPolygon" parameterType="string" value=""/>',
     'empty'),
    ('<ParameterDeclaration name="IslandOddMaxSpeed" parameterType="double" value="30"/>'
     '<ParameterDeclaration name="IslandOddMaxSpeed" parameterType="double" value="20"/>',
     'twice'),
])
def test_refused(tmp_path, decls, msg):
    with pytest.raises(ValueError, match=msg):
        read_scenario_odd(xosc(tmp_path, decls))


def test_inside_is_even_odd():
    sq = parse_polygon('0,0;10,0;10,10;0,10')
    assert inside(sq, 5, 5)
    assert not inside(sq, 11, 5)
    assert not inside(sq, 5, -1)
