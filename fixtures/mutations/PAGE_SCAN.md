# Doc A Page Scan

## Page 1
```
Selective Coordination Study –
Recommended Procedures
14
The following steps are recommended when
conducting a selective coordination study.
1. One-Line Diagram
Obtain the electrical system one-line diagram that identifies
important system components, as given below.
a. Transformers
Obtain the following data for protection and coordination infor-
mation of transformers:
- KVA rating
- Inrush points
- Primary and secondary connections
- Impedance
- Damage curves
- Primary and secondary voltages
- Liquid or dry type
b. Conductors - Check phase, neutral, and equipment
grounding. The one-line diagram should include infor-
mation such as:
- Conductor size
- Number of conductors per phase
- Material (copper or aluminum)
- Insulation
- Conduit (magnetic or non-magnetic)
From this information, short circuit withstand curves can be
developed. This provides information on how overcurrent
devices will protect conductors from overload and short
circuit damage.
c. Motors
The system one-line diagram should include motor
information such as:
- Full load currents
- Horsepower
- Voltage
- Type of starting characteristic 
(across the line, etc.)
- Type of overload relay 
(Class 10, 20, 30)
Overload protection of the motor and motor circuit can be
determined from this data.
d. Fuse Characteristics
Fuse Types/Classes should be identified on the one-line
diagram.
e. Circuit Breaker Characteristics
Circuit Breaker Types should be identified on the one-line
diagram.
f. Relay Characteristics
Relay Types should be identified on the one-line diagram.
2. Short Circuit Study
Perform a short circuit analysis, calculating maximum
available short circuit currents at critical points in the
distribution system (such as transformers, main switchgear,
panelboards, motor control centers, load centers, and large
motors and generators.) (Reference: Bussmann Bulletin,
Engineering Dependable Protection - EDPI.)
3. Helpful Hints
a. Determine the Ampere Scale Selection. It is most
convenient to place the time current curves in the center of
the log-log paper. This is accomplished by multiplying or
dividing the ampere scale by a factor of 10.
b. Determine the Reference (Base) Voltage. The best
reference voltage is the voltage level at which most of the
devices being studied fall. (On most low voltage industrial
and commercial studies, the reference voltage will be 208,
240, or 480 volts). Devices at other voltage levels will be
shifted by a multiplier based on the transformer turn ratio.
The best reference voltage will require the least amount of
manipulation. Modern computer programs will automat-
ically make these adjustments when the voltage levels of
devices are identified by the input data.
c. Commencing the Analysis. The starting point can be
determined by the designer. Typically, studies begin with
the main circuit devices and work down through the
feeders and branches. (Right to left on your log-log paper.)
d. Multiple Branches. If many branches are taken off one
feeder, and the branch loads are similar, the largest rated
branch circuit should be checked for coordination with
upstream devices. If the largest branch will coordinate, and
the branch devices are similar, they generally will
coordinate as well. (The designer may wish to verify other
areas of protection on those branches, conductors, etc.)
e. Don't Overcrowd the Study. Many computer generated
studies will allow a maximum of ten device characteristics
per page.
f. One-Line Diagram. A one-line diagram of the study
should be drawn for future reference.

```

## Page 2
```
The following pages will analyze in detail the system
shown in Figure 11. It is understood that a short circuit
study has been completed, and all devices have adequate
interrupting ratings. A Selective Coordination Analysis is the
next step.
Examples of Selective Coordination Studies
15
M
JCN80E
IFLA=42A
5.75% Z
1000KVA
∆-Y
480/277V
LOW-PEAK®
KRP-C-1600SP
Fault X1 20,000A RMS Sym
Main Switchboard
1
LOW PEAK®
LPS-RK-200SP
LOW-PEAK®
LPS-RK-400SP
LOW-PEAK®
LPS-RK-225SP
200A Feeder
400A Feeder
150KVA
∆-Y
208/120V
2% Z
LOW-PEAK®
LPN-RK-500SP
LOW-PEAK®
LPS-RK-100SP
20A Branch
20A CB
20A CB
LP1
60HP 3Ø
77A FLA
1600A Main Bus
PDP
13.8KV
Overcurrent Relay
#6 XLP
#3/0 THW
100A Motor Branch
#1 THW
250 kcmil
2/Ø THW
#12 THW
This simple radial system will involve three separate
time current curve studies, applicable to the three feeder/
branches shown.
Figure 11

```

## Page 3
```
Example –
Time Current Curve #1 (TCC1)
16
Device ID
Description
Comments
1
1000KVA XFMR
12 x FLA
Inrush Point
@ .1 Seconds
2
1000KVA XFMR
5.75%Z, liquid
Damage Curves
filled
(Footnote 1)
(Footnote 2)
3
JCN 80E
E-Rated Fuse
4
#6 Conductor
Copper, XLP
Damage Curve
Insulation
5
Medium Voltage
Needed for XFMR
Relay
Primary Overload
Protection
6
KRP-C-1600SP
Class L Fuse
11
LPS-RK-200SP
Class RK1 Fuse
12
3/0 Conductor
Copper THW
Damage Curve
Insulation
13
20A CB
Thermal Magnetic
Circuit Breaker
14
#12 Conductor
Copper THW
Damage Curve
Insulation
Footnote 1: Transformer damage curves indicate when it will be damaged,
thermally and/or mechanically, under overcurrent conditions.
Transformer impedance, as well as primary and secondary
connections, and type, all will determine their damage
characteristics.
Footnote 2: A ∆-Y transformer connection requires a 15% shift, to the right,
of the L-L thermal damage curve. This is due to a L-L
secondary fault condition, which will cause 1.0 p.u. to flow
through one primary phase, and .866 p.u. through the two
faulted secondary phases. (These currents are p.u. of 3-phase
fault current.)
Notes:
1. TCC1 includes the primary fuse, secondary main fuse,
200 ampere feeder fuse, and 20 ampere branch circuit
breaker from LP1.
2. Analysis will begin at the main devices and proceed
down through the system.
3. Reference (base) voltage will be 480 volts, arbitrarily
chosen since most of the devices are at this level.
4. Selective coordination between the feeder and branch
circuit is not attainable for faults above 2500 amperes that
occur on the 20 amp branch circuit, from LP1. Notice the
overlap of the 200 ampere fuse and 20 ampere circuit
breaker.
5. The required minimum ratio of 2:1 is easily met between
the KRP-C-1600SP and the LPS-RK-200SP.

```

## Page 4
```
Example –
Time Current Curve #1 (TCC1)
17
CURRENT IN AMPERES X 10 @ 480V
TIME IN SECONDS
FLA
11
2
2
3
5
12
14
13
1
6
#12 DAMAGE
3/0 DAMAGE
20A MCCB
XFMR
DAMAGE
4
JCN 80E
MV OLR
1000KVA
5.75%Z
∆-Y
480/277V
JCN80E
13.8KV
KRP-C-1600SP
LPS-RK-200SP
200A 
Feeder
#6 XLP
#3/0 THW
Overcurrent
Relay
20A CB
#12 THW
20A CB
KRP-C-1600SP
TX
INRUSH
600
400
300
200
100
80
60
40
30
20
10
8
6
4
3
2
1
.8
.6
.4
.3
.2
.1
.08
.04
.06
.03
.02
.01
800
1000
1
2
3
4
6
8
10
20
30
40
60
80
100
200
300
400
600
800
1000
2000
3000
4000
6000
8000
10,000
LPS-RK-200SP
#6 DAMAGE

```

## Page 5
```
Example –
Time Current Curve #2 (TCC2)
18
Notes:
1. TCC2 includes the primary fuse, secondary main fuse,
400 ampere feeder fuse, 100 ampere motor branch fuse,
77 ampere motor and overload relaying.
2. Analysis will begin at the main devices and proceed
down through the system.
3. Reference (base) voltage will be 480 volts, arbitrarily
chosen since most of the devices are at this level.
Device ID
Description
Comment
1
1000KVA XFMR
12 x FLA
Inrush Point
@ .1 seconds
2
1000KVA XFMR
5.75%Z, liquid
Damage Curves
filled
(Footnote 1)
(Footnote 2)
3
JCN 80E
E-Rated Fuse
4
#6 Conductor
Copper, XLP
Damage Curve
Insulation
5
Medium Voltage
Needed for XFMR
Relay
Primary Overload
Protection
6
KRP-C-1600SP
Class L Fuse
21
LPS-RK-100SP
Class RK1 Fuse
22
Motor Starting Curve
Across the Line 
Start
23
Motor Overload Relay
Class 10
24
Motor Stall Point
Part of a Motor 
Damage Curve
25
#1 Conductor
Copper THW
Damage Curve
Insulation
Footnote 1: Transformer damage curves indicate when it will be damaged,
thermally and/or mechanically, under overcurrent conditions.
Transformer impedance, as well as primary and secondary
connections, and type, all will determine their damage
characteristics.
Footnote 2: A ∆-Y transformer connection requires a 15% shift, to the right,
of the L-L thermal damage curve. This is due to a L-L
secondary fault condition, which will cause 1.0 p.u. to flow
through one primary phase, and .866 p.u. through the two
faulted secondary phases. (These currents are p.u. of 3-phase
fault current.)

```

## Page 6
```
Example –
Time Current Curve #2 (TCC2)
19
KRP-C-1600SP
LPS-RK-400SP
LPS-RK-100SP
60HP
400A Feeder
CURRENT IN AMPERES X 10 @ 480V
TIME IN SECONDS
MV OLR
2
2
3
5
1
6
4
21
22
25
23
24
FLA
MS
JCN80E
MTR START
LPS-RK-100SP
MTR OLR
XFMR DAMAGE
M
#1 THW
TX
INRUSH
#6 XLP
13.8KV
Overcurrent
Relay
JCN 80E
1000KVA
5.75%Z
∆-Y
480/277V
600
400
300
200
100
80
60
40
30
20
10
8
6
4
3
2
1
.8
.6
.4
.3
.2
.1
.08
.04
.06
.03
.02
.01
800
1000
1
2
3
4
6
8
10
20
30
40
60
80
100
200
300
400
600
800
1000
2000
3000
4000
6000
8000
10,000
KRP-C-1600SP
#1 DAMAGE
#6 DAMAGE

```

## Page 7
```
Example –
Time Current Curve #3 (TCC3)
20
Notes:
1. TCC3 includes the primary fuse, secondary main fuse,
225 ampere feeder/transformer primary and secondary
fuses.
2. Analysis will begin at the main devices and proceed
down through the system.
3. Reference (base) voltage will be 480 volts, arbitrarily
chosen since most of the devices are at this level.
4. Relative to the 225 ampere feeder, coordination between
primary and secondary fuses is not attainable, noted by
overlap of curves.
5. Overload and short circuit protection for the 150 KVA
transformer is afforded by the LPS-RK-225SP fuse.
Device ID
Description
Comment
1
1000KVA XFMR
12 x FLA
Inrush Point
@ .1 seconds
2
1000KVA XFMR
5.75%Z, liquid
Damage Curves
filled
(Footnote 1)
(Footnote 2)
3
JCN 80E
E-Rated Fuse
4
#6 Conductor
Copper, XLP
Damage Curve
Insulation
5
Medium Voltage
Needed for XFMR
Relay
Primary Overload
Protection
6
KRP-C-1600SP
Class L Fuse
31
LPS-RK-225SP
Class RK1 Fuse
32
150 KVA XFMR
12 x FLA
Inrush Point
@.1 Seconds
33
150 KVA XFMR
2.00% Dry Type
Damage Curves
(Footnote 3)
34
LPN-RK-500SP
Class RK1 Fuse
35
2-250kcmil Conductors
Copper THW
Damage Curve
Insulation
Footnote 1: Transformer damage curves indicate when it will be damaged,
thermally and/or mechanically, under overcurrent conditions.
Transformer impedance, as well as primary and secondary
connections, and type, all will determine their damage
characteristics.
Footnote 2: A ∆-Y transformer connection requires a 15% shift, to the right,
of the L-L thermal damage curve. This is due to a L-L
secondary fault condition, which will cause 1.0 p.u. to flow
through one primary phase, and .866 p.u. through the two
faulted secondary phases. (These currents are p.u. of 3-phase
fault current.)
Footnote 3: Damage curves for a small KVA (<500KVA) transformer,
illustrate thermal damage characteristics for ∆-Y connected.
From right to left, these reflect damage characteristics, for a
line-line fault, 3Ø fault, and L-G fault condition.

```

## Page 8
```
Example –
Time Current Curve #3 (TCC3)
21
CURRENT IN AMPERES X 10 @ 480V
600
400
300
200
100
80
60
40
30
20
10
8
6
4
3
2
1
.8
.6
.4
.3
.2
.1
.08
.04
.06
.03
.02
.01
TIME IN SECONDS
800
1000
4
5
2
FLA
FLA
MV OLR
XFMR DAMAGE
JCN80E
XFMR DAMAGE
33
35
LPS-RK-225SP
LPN-RK-500SP
KRP-C-1600SP
TX
INRUSH
TX
INRUSH
1
32
6
#6 XLP
JCN 80E
13.8KV
Overcurrent
Relay
250 kcmil
2/Ø THW
31
34
KRP-C1600SP
2
3
1000KVA
5.75%Z
∆-Y
480/277V
150KVA
2.0%Z
∆-Y
208/120V
1
2
3
4
6
8
10
20
30
40
60
80
100
200
300
400
600
800
1000
2000
3000
4000
6000
8000
10,000
LPS-RK-225SP
LPN-RK-500SP
2-250 DAMAGE
#6 DAMAGE

```

## Page 9
```
Unnecessary power OUTAGES, such as the
BLACKOUTS we so often experience, can be stopped by
isolating a faulted circuit from the remainder of the system
through the proper selection of MODERN CURRENT-
LIMITING FUSES.
Time-Delay type current-limiting fuses can be sized
close to the load current and still hold motor-starting
currents or other harmless transients, thereby
ELIMINATING nuisance OUTAGES.
The SELECTIVITY GUIDE on page 10 may be used for
an easy check on fuse selectivity regardless of the short-
circuit current levels involved. Where medium and high
voltage primary fuses are involved, the time-current
characteristic curves of the fuses in question should be
plotted on standard NEMA log-log graph paper for proper
study.
The time saved by using the SELECTIVITY GUIDE will
allow the electrical systems designer to pursue other areas
for improved systems design.
Conclusions
22

```
