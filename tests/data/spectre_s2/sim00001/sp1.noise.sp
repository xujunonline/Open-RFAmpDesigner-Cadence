HEADER
"PSFversion" "1.00"
"simulator" "spectre"
"version" "25.1.0.054"
"date" "3:20:52 PM, Thur Oct 1, 2026"
"design" "// orfadc.repro Spectre macromodel netlist (auto-generated; not a PDK netlist)"
"analysis type" "noise.sp"
"analysis name" "sp1"
"analysis description" "S-Parameter Analysis `sp1': freq = 30 GHz"
"xVecSorted" "unknown"
"tolerance.relative" 1.000000000000000e-03
"operating point producer" "sp1"
"output" "probe"
"output probe" "PORT2"
"output probe type" "voltage"
"ground" "0"
"positive output signal" "d2"
"negative output signal" "0"
"input probe" "PORT1"
TYPE
"sweep" FLOAT DOUBLE PROP(
"key" "sweep"
)
"V/sqrt(Hz)" FLOAT DOUBLE PROP(
"units" "V/sqrt(Hz)"
"key" "noise"
)
"V^2/Hz" FLOAT DOUBLE PROP(
"units" "V^2/Hz"
"key" "noise"
)
"V/V" FLOAT DOUBLE PROP(
"units" "V/V"
"key" "noise"
)
"Noise factor" FLOAT DOUBLE PROP(
"units" "(V^2/Hz)/(V^2/Hz)"
"key" "noise"
)
"dB" FLOAT DOUBLE PROP(
"units" "dB"
"key" "noise"
)
"inductor" STRUCT(
"rn" FLOAT DOUBLE PROP(
"units" "V^2/Hz"
"noise_type" "thermal"
)
"fn" FLOAT DOUBLE PROP(
"units" "V^2/Hz"
"noise_type" "flicker"
)
"total" FLOAT DOUBLE PROP(
"units" "V^2/Hz"
)
) PROP(
"key" "inst"
"master" "inductor"
)
"PORT2" STRUCT(
"rn" FLOAT DOUBLE PROP(
"units" "V^2/Hz"
)
"ext_file_noise" FLOAT DOUBLE PROP(
"units" "V^2/Hz"
)
"total" FLOAT DOUBLE PROP(
"units" "V^2/Hz"
)
) PROP(
"key" "inst"
"master" "port"
)
"PORT1" STRUCT(
"rn" FLOAT DOUBLE PROP(
"units" "V^2/Hz"
)
"ext_file_noise" FLOAT DOUBLE PROP(
"units" "V^2/Hz"
)
"total" FLOAT DOUBLE PROP(
"units" "V^2/Hz"
)
) PROP(
"key" "inst"
"master" "port"
)
"resistor" STRUCT(
"rn" FLOAT DOUBLE PROP(
"units" "V^2/Hz"
"noise_type" "thermal"
)
"total" FLOAT DOUBLE PROP(
"units" "V^2/Hz"
)
) PROP(
"key" "inst"
"master" "resistor"
)
"S" FLOAT DOUBLE PROP(
"units" "S"
"key" "noise"
)
"Ohm" FLOAT DOUBLE PROP(
"units" "Ohm"
"key" "noise"
)
"Ohm/Ohm" FLOAT DOUBLE PROP(
"units" "Ohm/Ohm"
"key" "noise"
)
SWEEP
"freq" "sweep" PROP(
"sweep_direction" 0
"units" "Hz"
"plot" 0
"grid" 1
)
TRACE
"Lk12s" "inductor"
"Lk12p" "inductor"
"Lxl10" "inductor"
"Lxl2" "inductor"
"Lxl1" "inductor"
"PORT2" "PORT2"
"PORT1" "PORT1"
"Rwn17" "resistor"
"Rwn14" "resistor"
"Rm13ds" "resistor"
"RG2" "resistor"
"Rk12g2" "resistor"
"Rk12d1" "resistor"
"Rk12s" "resistor"
"Rk12p" "resistor"
"Rwn11" "resistor"
"RCGds" "resistor"
"Rxl10" "resistor"
"Rwn7" "resistor"
"Rwn4" "resistor"
"Rm3ds" "resistor"
"RG1" "resistor"
"Rxl2" "resistor"
"Rxl1" "resistor"
"out" "V/sqrt(Hz)"
"Fmin" "Noise factor"
"NFmin" "dB"
"F" "Noise factor"
"NF" "dB"
"Gopt" "S"
"Bopt" "S"
"RN" "Ohm"
"NNR" "Ohm/Ohm"
VALUE
"freq" 3.000000000000000e+10
"Lk12s" (
0.000000000000000e+00
0.000000000000000e+00
0.000000000000000e+00
)
"Lk12p" (
0.000000000000000e+00
0.000000000000000e+00
0.000000000000000e+00
)
"Lxl10" (
0.000000000000000e+00
0.000000000000000e+00
0.000000000000000e+00
)
"Lxl2" (
0.000000000000000e+00
0.000000000000000e+00
0.000000000000000e+00
)
"Lxl1" (
0.000000000000000e+00
0.000000000000000e+00
0.000000000000000e+00
)
"PORT2" (
9.467141739946253e-19
0.000000000000000e+00
9.467141739946253e-19
)
"PORT1" (
1.091030399636995e-17
0.000000000000000e+00
1.091030399636995e-17
)
"Rwn17" (
9.368946507877630e-19
9.368946507877630e-19
)
"Rwn14" (
5.506746329881287e-18
5.506746329881287e-18
)
"Rm13ds" (
0.000000000000000e+00
0.000000000000000e+00
)
"RG2" (
1.600152695772284e-20
1.600152695772284e-20
)
"Rk12g2" (
7.008502332411984e-19
7.008502332411984e-19
)
"Rk12d1" (
4.864070392495894e-19
4.864070392495894e-19
)
"Rk12s" (
1.171856159646894e-19
1.171856159646894e-19
)
"Rk12p" (
1.471558206666776e-19
1.471558206666776e-19
)
"Rwn11" (
2.743384014684188e-18
2.743384014684188e-18
)
"RCGds" (
0.000000000000000e+00
0.000000000000000e+00
)
"Rxl10" (
9.456168978261554e-20
9.456168978261554e-20
)
"Rwn7" (
9.362452814820485e-19
9.362452814820485e-19
)
"Rwn4" (
1.995114874537400e-18
1.995114874537400e-18
)
"Rm3ds" (
0.000000000000000e+00
0.000000000000000e+00
)
"RG1" (
3.405944238932971e-19
3.405944238932971e-19
)
"Rxl2" (
2.017444396489024e-19
2.017444396489024e-19
)
"Rxl1" (
2.605573947290877e-19
2.605573947290877e-19
)
"out" 5.132295929296268e-09
"Fmin" 2.305004758149363e+00
"NFmin" 3.626718262271331e+00
"F" 2.327501354712514e+00
"NF" 3.668899424327565e+00
"Gopt" 2.377993307468076e-02
"Bopt" 3.383460119917869e-03
"RN" 1.748279602416887e+01
"NNR" 3.496559204833775e-01
END
