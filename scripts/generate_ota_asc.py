"""
Miller OTA Schematic Generator for LTspice.
Synthesizes a 2-stage CMOS Miller Operational Transconductance Amplifier
with parametric compensation capacitor Cc for arbitrary GBW targets.
"""

from pathlib import Path

def generate_miller_ota_asc(cc_pf: float, target_gbw_mhz: float, output_path: Path) -> str:
    content = f"""Version 4
SHEET 1 1400 900
WIRE 112 112 112 160
WIRE 112 240 112 304
WIRE 192 112 192 160
WIRE 192 240 192 304
WIRE 272 112 272 160
WIRE 272 240 272 304
WIRE 400 112 400 160
WIRE 400 240 400 304
WIRE 512 112 512 160
WIRE 512 224 512 304
WIRE 640 112 640 160
WIRE 640 224 640 304
FLAG 112 112 VDD
FLAG 112 304 0
FLAG 192 112 INP
FLAG 192 304 0
FLAG 272 112 INM
FLAG 272 304 0
FLAG 400 112 VDD
FLAG 400 304 NBIAS
FLAG 512 112 N_INT
FLAG 512 304 VOUT
FLAG 640 112 VOUT
FLAG 640 304 0
SYMBOL voltage 112 144 R0
WINDOW 123 0 0 Left 0
WINDOW 39 0 0 Left 0
SYMATTR InstName Vdd
SYMATTR Value 3.3
SYMBOL voltage 192 144 R0
WINDOW 123 0 0 Left 0
WINDOW 39 0 0 Left 0
SYMATTR InstName Vin
SYMATTR Value 1.65
SYMATTR Value2 AC 1
SYMBOL voltage 272 144 R0
WINDOW 123 0 0 Left 0
WINDOW 39 0 0 Left 0
SYMATTR InstName Vref
SYMATTR Value 1.65
SYMBOL current 400 160 R0
WINDOW 123 0 0 Left 0
WINDOW 39 0 0 Left 0
SYMATTR InstName Ibias
SYMATTR Value 50u
SYMBOL cap 496 160 R0
SYMATTR InstName Cc
SYMATTR Value {cc_pf}p
SYMBOL cap 624 160 R0
SYMATTR InstName CL
SYMATTR Value 5p
TEXT 112 360 Left 2 ;Two-Stage CMOS Miller OTA (Target GBW = {target_gbw_mhz} MHz, Cc = {cc_pf}pF)
TEXT 112 400 Left 2 !.ac dec 50 10 1G
TEXT 112 440 Left 2 !.meas AC A0 FIND mag(V(VOUT)) AT 10
TEXT 112 480 Left 2 !.meas AC GBW WHEN mag(V(VOUT))=1
TEXT 112 520 Left 2 !.meas AC Phase_at_GBW FIND ph(V(VOUT)) WHEN mag(V(VOUT))=1
TEXT 112 560 Left 2 !.model NMOS NMOS(Level=1 Vto=0.7 Kp=100u Lambda=0.02)
TEXT 112 600 Left 2 !.model PMOS PMOS(Level=1 Vto=-0.7 Kp=40u Lambda=0.02)
TEXT 112 640 Left 2 !M8 NBIAS NBIAS 0 0 NMOS W=10u L=1u
TEXT 112 680 Left 2 !M5 NTAIL NBIAS 0 0 NMOS W=20u L=1u
TEXT 112 720 Left 2 !M1 ND1 INP NTAIL 0 NMOS W=20u L=1u
TEXT 112 760 Left 2 !M2 N_INT INM NTAIL 0 NMOS W=20u L=1u
TEXT 112 800 Left 2 !M3 ND1 ND1 VDD VDD PMOS W=25u L=1u
TEXT 112 840 Left 2 !M4 N_INT ND1 VDD VDD PMOS W=25u L=1u
TEXT 112 880 Left 2 !M6 VOUT N_INT VDD VDD PMOS W=50u L=1u
TEXT 112 920 Left 2 !M7 VOUT NBIAS 0 0 NMOS W=20u L=1u
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return content

if __name__ == "__main__":
    p = Path(__file__).resolve().parent.parent / "outputs" / "miller_ota.asc"
    generate_miller_ota_asc(cc_pf=7.0, target_gbw_mhz=10.0, output_path=p)
    print(f"Generated Miller OTA schematic at {p}")
