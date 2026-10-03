HEADER
"PSFversion" "1.00"
"simulator" "spectre"
"version" "25.1.0.054"
"date" "3:20:52 PM, Thur Oct 1, 2026"
"design" "// orfadc.repro Spectre macromodel netlist (auto-generated; not a PDK netlist)"
"analysis type" "sp"
"analysis name" "sp1"
"analysis description" "S-Parameter Analysis `sp1': freq = 30 GHz"
"xVecSorted" "unknown"
"tolerance.relative" 1.000000000000000e-03
"mode" "ss"
"number of ports" 2
"PORT1:r" 5.000000000000000e+01
"PORT1:num" 1
"PORT1:units" "Ohm"
"PORT2:r" 2.500000000000000e+02
"PORT2:num" 2
"PORT2:units" "Ohm"
TYPE
"sweep" FLOAT DOUBLE PROP(
"key" "sweep"
)
"S-Param" COMPLEX DOUBLE PROP(
"key" "SP"
)
SWEEP
"freq" "sweep" PROP(
"sweep_direction" 0
"units" "Hz"
)
TRACE
"s11" "S-Param"
"s21" "S-Param"
"s12" "S-Param"
"s22" "S-Param"
"cy11" "S-Param"
"cy21" "S-Param"
"cy12" "S-Param"
"cy22" "S-Param"
VALUE
"freq" 3.000000000000000e+10
"s11" (-4.904896765198474e-02 5.416704219874838e-02)
"s21" (-1.494079930172658e+00 2.944088844609163e+00)
"s12" (5.243595571719713e-04 3.976060562567085e-05)
"s22" (-3.602372795619193e-01 -7.324738916548715e-01)
"cy11" (7.905019193954640e-03 5.696296570285170e-20)
"cy21" (8.478983840031366e-03 -3.854152043975832e-03)
"cy12" (8.478983840031363e-03 3.854152043975831e-03)
"cy22" (7.080629317881863e-02 -1.301042606982605e-18)
END
