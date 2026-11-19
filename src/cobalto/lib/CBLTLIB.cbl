      *================================================================
      * Cobalto (CBLT) - Assert library. COBOL 85, fixed format.
      * Programs: CBLTINI CBLTREC CBLTCAS CBLTEQ CBLTNE CBLTEQN CBLTCT
      *            CBLTGT CBLTLT CBLTBT CBLTCOV
      * Use from a test:
      *     MOVE "expected" TO CBLT-EXP
      *     MOVE WS-FIELD   TO CBLT-ACT
      *     CALL "CBLTEQ" USING CBLT-CTX
      *================================================================
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CBLTINI.
      * Initializes the context for a test.
       DATA DIVISION.
       LINKAGE SECTION.
       01  CBLT-CTX.
           COPY CBLTCTX.
       01  L-NAME                    PIC X(30).
       PROCEDURE DIVISION USING CBLT-CTX L-NAME.
       MAIN.
           MOVE L-NAME TO CBLT-TEST-NAME.
           MOVE ZERO TO CBLT-ASSERT-COUNT CBLT-FAIL-COUNT
                        CBLT-LOG-COUNT.
           MOVE SPACES TO CBLT-MSG CBLT-EXP CBLT-ACT.
           MOVE ZERO TO CBLT-EXP-NUM CBLT-ACT-NUM CBLT-EXP-NUM2.
           EXIT PROGRAM.
       END PROGRAM CBLTINI.

       IDENTIFICATION DIVISION.
       PROGRAM-ID. CBLTREC.
      * Records the result of an assert in the log of the context.
      * Control characters (binary bytes of an uninitialized field)
      * are replaced by "?" so that the results file stays plain
      * text.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-I                      PIC 9(3).
       LINKAGE SECTION.
       01  CBLT-CTX.
           COPY CBLTCTX.
       01  L-STATUS                  PIC X.
       01  L-KIND                    PIC X(8).
       01  L-EXP                     PIC X(60).
       01  L-ACT                     PIC X(60).
       PROCEDURE DIVISION USING CBLT-CTX L-STATUS L-KIND L-EXP L-ACT.
       MAIN.
           ADD 1 TO CBLT-ASSERT-COUNT.
           IF L-STATUS = "F"
               ADD 1 TO CBLT-FAIL-COUNT
           END-IF.
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 60
               IF L-EXP(WS-I:1) < SPACE
                   MOVE "?" TO L-EXP(WS-I:1)
               END-IF
               IF L-ACT(WS-I:1) < SPACE
                   MOVE "?" TO L-ACT(WS-I:1)
               END-IF
               IF CBLT-MSG(WS-I:1) < SPACE
                   MOVE "?" TO CBLT-MSG(WS-I:1)
               END-IF
           END-PERFORM.
           IF CBLT-LOG-COUNT < 500
               ADD 1 TO CBLT-LOG-COUNT
               MOVE L-STATUS TO CBLT-LOG-STATUS(CBLT-LOG-COUNT)
               MOVE CBLT-ASSERT-COUNT TO CBLT-LOG-NR(CBLT-LOG-COUNT)
               MOVE L-KIND TO CBLT-LOG-KIND(CBLT-LOG-COUNT)
               MOVE L-EXP TO CBLT-LOG-EXP(CBLT-LOG-COUNT)
               MOVE L-ACT TO CBLT-LOG-ACT(CBLT-LOG-COUNT)
               MOVE CBLT-MSG TO CBLT-LOG-MSG(CBLT-LOG-COUNT)
           END-IF.
           MOVE SPACES TO CBLT-MSG.
           EXIT PROGRAM.
       END PROGRAM CBLTREC.

       IDENTIFICATION DIVISION.
       PROGRAM-ID. CBLTEQ.
      * Assert: CBLT-EXP = CBLT-ACT (alphanumeric; trailing spaces are
      * ignored by the COBOL comparison rule).
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STATUS                 PIC X.
       01  WS-KIND                   PIC X(8) VALUE "EQUALS".
       01  WS-EXP                    PIC X(60).
       01  WS-ACT                    PIC X(60).
       LINKAGE SECTION.
       01  CBLT-CTX.
           COPY CBLTCTX.
       PROCEDURE DIVISION USING CBLT-CTX.
       MAIN.
           IF CBLT-EXP = CBLT-ACT
               MOVE "P" TO WS-STATUS
           ELSE
               MOVE "F" TO WS-STATUS
           END-IF.
           MOVE CBLT-EXP TO WS-EXP.
           MOVE CBLT-ACT TO WS-ACT.
           CALL "CBLTREC" USING CBLT-CTX WS-STATUS WS-KIND
                                WS-EXP WS-ACT.
           EXIT PROGRAM.
       END PROGRAM CBLTEQ.

       IDENTIFICATION DIVISION.
       PROGRAM-ID. CBLTNE.
      * Assert: CBLT-EXP NOT = CBLT-ACT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STATUS                 PIC X.
       01  WS-KIND                   PIC X(8) VALUE "NOTEQUAL".
       01  WS-EXP                    PIC X(60).
       01  WS-ACT                    PIC X(60).
       LINKAGE SECTION.
       01  CBLT-CTX.
           COPY CBLTCTX.
       PROCEDURE DIVISION USING CBLT-CTX.
       MAIN.
           IF CBLT-EXP NOT = CBLT-ACT
               MOVE "P" TO WS-STATUS
           ELSE
               MOVE "F" TO WS-STATUS
           END-IF.
           MOVE CBLT-EXP TO WS-EXP.
           MOVE CBLT-ACT TO WS-ACT.
           CALL "CBLTREC" USING CBLT-CTX WS-STATUS WS-KIND
                                WS-EXP WS-ACT.
           EXIT PROGRAM.
       END PROGRAM CBLTNE.

       IDENTIFICATION DIVISION.
       PROGRAM-ID. CBLTEQN.
      * Numeric assert: CBLT-EXP-NUM = CBLT-ACT-NUM.
      * Compares the value, not the storage (COMP-3, binary, display).
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STATUS                 PIC X.
       01  WS-KIND                   PIC X(8) VALUE "EQNUM".
       01  WS-EXP                    PIC X(60).
       01  WS-ACT                    PIC X(60).
       01  WS-EDIT                   PIC -(15)9.9(3).
       LINKAGE SECTION.
       01  CBLT-CTX.
           COPY CBLTCTX.
       PROCEDURE DIVISION USING CBLT-CTX.
       MAIN.
           IF CBLT-EXP-NUM = CBLT-ACT-NUM
               MOVE "P" TO WS-STATUS
           ELSE
               MOVE "F" TO WS-STATUS
           END-IF.
           MOVE CBLT-EXP-NUM TO WS-EDIT.
           MOVE WS-EDIT TO WS-EXP.
           MOVE CBLT-ACT-NUM TO WS-EDIT.
           MOVE WS-EDIT TO WS-ACT.
           CALL "CBLTREC" USING CBLT-CTX WS-STATUS WS-KIND
                                WS-EXP WS-ACT.
           EXIT PROGRAM.
       END PROGRAM CBLTEQN.

       IDENTIFICATION DIVISION.
       PROGRAM-ID. CBLTCT.
      * Assert: CBLT-ACT contains CBLT-EXP (without trailing spaces).
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STATUS                 PIC X.
       01  WS-KIND                   PIC X(8) VALUE "CONTAINS".
       01  WS-EXP                    PIC X(60).
       01  WS-ACT                    PIC X(60).
       01  WS-LEN                    PIC 9(3).
       01  WS-I                      PIC 9(3).
       01  WS-MAX                    PIC 9(3).
       LINKAGE SECTION.
       01  CBLT-CTX.
           COPY CBLTCTX.
       PROCEDURE DIVISION USING CBLT-CTX.
       MAIN.
           MOVE 0 TO WS-LEN.
           PERFORM VARYING WS-I FROM 256 BY -1
               UNTIL WS-I = 0 OR WS-LEN > 0
               IF CBLT-EXP(WS-I:1) NOT = SPACE
                   MOVE WS-I TO WS-LEN
               END-IF
           END-PERFORM.
           MOVE "F" TO WS-STATUS.
           IF WS-LEN = 0
               MOVE "P" TO WS-STATUS
           ELSE
               COMPUTE WS-MAX = 256 - WS-LEN + 1
               PERFORM VARYING WS-I FROM 1 BY 1
                   UNTIL WS-I > WS-MAX OR WS-STATUS = "P"
                   IF CBLT-ACT(WS-I:WS-LEN) = CBLT-EXP(1:WS-LEN)
                       MOVE "P" TO WS-STATUS
                   END-IF
               END-PERFORM
           END-IF.
           MOVE CBLT-EXP TO WS-EXP.
           MOVE CBLT-ACT TO WS-ACT.
           CALL "CBLTREC" USING CBLT-CTX WS-STATUS WS-KIND
                                WS-EXP WS-ACT.
           EXIT PROGRAM.
       END PROGRAM CBLTCT.

       IDENTIFICATION DIVISION.
       PROGRAM-ID. CBLTCAS.
      * Marks the start of a test case (L-STAT "C") or of an ignored
      * one (L-STAT "I") in the log. It does not count as an assert.
       DATA DIVISION.
       LINKAGE SECTION.
       01  CBLT-CTX.
           COPY CBLTCTX.
       01  L-NAME                    PIC X(60).
       01  L-STAT                    PIC X.
       PROCEDURE DIVISION USING CBLT-CTX L-NAME L-STAT.
       MAIN.
           IF CBLT-LOG-COUNT < 500
               ADD 1 TO CBLT-LOG-COUNT
               MOVE L-STAT TO CBLT-LOG-STATUS(CBLT-LOG-COUNT)
               MOVE ZERO TO CBLT-LOG-NR(CBLT-LOG-COUNT)
               MOVE "CASE" TO CBLT-LOG-KIND(CBLT-LOG-COUNT)
               MOVE L-NAME TO CBLT-LOG-EXP(CBLT-LOG-COUNT)
               MOVE SPACES TO CBLT-LOG-ACT(CBLT-LOG-COUNT)
               MOVE SPACES TO CBLT-LOG-MSG(CBLT-LOG-COUNT)
           END-IF.
           MOVE SPACES TO CBLT-MSG.
           EXIT PROGRAM.
       END PROGRAM CBLTCAS.

       IDENTIFICATION DIVISION.
       PROGRAM-ID. CBLTGT.
      * Numeric assert: CBLT-ACT-NUM > CBLT-EXP-NUM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STATUS                 PIC X.
       01  WS-KIND                   PIC X(8) VALUE "GREATER".
       01  WS-EXP                    PIC X(60).
       01  WS-ACT                    PIC X(60).
       01  WS-EDIT                   PIC -(15)9.9(3).
       LINKAGE SECTION.
       01  CBLT-CTX.
           COPY CBLTCTX.
       PROCEDURE DIVISION USING CBLT-CTX.
       MAIN.
           IF CBLT-ACT-NUM > CBLT-EXP-NUM
               MOVE "P" TO WS-STATUS
           ELSE
               MOVE "F" TO WS-STATUS
           END-IF.
           MOVE CBLT-EXP-NUM TO WS-EDIT.
           MOVE WS-EDIT TO WS-EXP.
           MOVE CBLT-ACT-NUM TO WS-EDIT.
           MOVE WS-EDIT TO WS-ACT.
           CALL "CBLTREC" USING CBLT-CTX WS-STATUS WS-KIND
                                WS-EXP WS-ACT.
           EXIT PROGRAM.
       END PROGRAM CBLTGT.

       IDENTIFICATION DIVISION.
       PROGRAM-ID. CBLTLT.
      * Numeric assert: CBLT-ACT-NUM < CBLT-EXP-NUM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STATUS                 PIC X.
       01  WS-KIND                   PIC X(8) VALUE "LESS".
       01  WS-EXP                    PIC X(60).
       01  WS-ACT                    PIC X(60).
       01  WS-EDIT                   PIC -(15)9.9(3).
       LINKAGE SECTION.
       01  CBLT-CTX.
           COPY CBLTCTX.
       PROCEDURE DIVISION USING CBLT-CTX.
       MAIN.
           IF CBLT-ACT-NUM < CBLT-EXP-NUM
               MOVE "P" TO WS-STATUS
           ELSE
               MOVE "F" TO WS-STATUS
           END-IF.
           MOVE CBLT-EXP-NUM TO WS-EDIT.
           MOVE WS-EDIT TO WS-EXP.
           MOVE CBLT-ACT-NUM TO WS-EDIT.
           MOVE WS-EDIT TO WS-ACT.
           CALL "CBLTREC" USING CBLT-CTX WS-STATUS WS-KIND
                                WS-EXP WS-ACT.
           EXIT PROGRAM.
       END PROGRAM CBLTLT.

       IDENTIFICATION DIVISION.
       PROGRAM-ID. CBLTBT.
      * Numeric assert: CBLT-EXP-NUM <= CBLT-ACT-NUM <= CBLT-EXP-NUM2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STATUS                 PIC X.
       01  WS-KIND                   PIC X(8) VALUE "BETWEEN".
       01  WS-EXP                    PIC X(60).
       01  WS-ACT                    PIC X(60).
       01  WS-EDIT                   PIC -(15)9.9(3).
       01  WS-EDIT2                  PIC -(15)9.9(3).
       LINKAGE SECTION.
       01  CBLT-CTX.
           COPY CBLTCTX.
       PROCEDURE DIVISION USING CBLT-CTX.
       MAIN.
           IF CBLT-ACT-NUM >= CBLT-EXP-NUM
              AND CBLT-ACT-NUM <= CBLT-EXP-NUM2
               MOVE "P" TO WS-STATUS
           ELSE
               MOVE "F" TO WS-STATUS
           END-IF.
           MOVE CBLT-EXP-NUM TO WS-EDIT.
           MOVE CBLT-EXP-NUM2 TO WS-EDIT2.
           MOVE SPACES TO WS-EXP.
           STRING WS-EDIT " .. " WS-EDIT2 DELIMITED BY SIZE
               INTO WS-EXP.
           MOVE CBLT-ACT-NUM TO WS-EDIT.
           MOVE WS-EDIT TO WS-ACT.
           CALL "CBLTREC" USING CBLT-CTX WS-STATUS WS-KIND
                                WS-EXP WS-ACT.
           EXIT PROGRAM.
       END PROGRAM CBLTBT.

       IDENTIFICATION DIVISION.
       PROGRAM-ID. CBLTCOV.
      * Portable coverage: accumulates the counters of the programs
      * instrumented by the CLI and hands them to the driver.
      * Op "F" (flush): the instrumented program sends its name, the
      *   number of counters and its table; they are added here and the
      *   table of the program goes back to zero.
      * Op "R" (read): the driver asks for the next non-zero counter;
      *   it returns L-OP "C" with name, index and count in L-NAME,
      *   L-N and L-TAB(1), or L-OP "E" when there are none left.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PROG-COUNT             PIC 9(3) VALUE 0.
       01  WS-USED                   PIC 9(5) VALUE 0.
       01  WS-PROGS.
           05  WS-PROG OCCURS 200 TIMES.
               10  WS-PROG-NAME      PIC X(30).
               10  WS-PROG-BASE      PIC 9(5).
               10  WS-PROG-N         PIC 9(5).
       01  WS-HITS.
           05  WS-HIT                PIC 9(9) OCCURS 30000 TIMES.
       01  WS-P                      PIC 9(3) VALUE 0.
       01  WS-I                      PIC 9(5) VALUE 0.
       01  WS-CUR-P                  PIC 9(3) VALUE 1.
       01  WS-CUR-I                  PIC 9(5) VALUE 0.
       01  WS-FOUND                  PIC X.
       LINKAGE SECTION.
       01  L-OP                      PIC X.
       01  L-NAME                    PIC X(30).
       01  L-N                       PIC 9(5).
       01  L-TAB.
           05  L-HIT                 PIC 9(9) OCCURS 9999 TIMES.
       PROCEDURE DIVISION USING L-OP L-NAME L-N L-TAB.
       COV-MAIN.
           IF L-OP = "F"
               PERFORM COV-FLUSH
           ELSE
               PERFORM COV-READ
           END-IF.
           EXIT PROGRAM.
       COV-FLUSH.
           MOVE "N" TO WS-FOUND.
           PERFORM VARYING WS-P FROM 1 BY 1
               UNTIL WS-P > WS-PROG-COUNT OR WS-FOUND = "Y"
               IF WS-PROG-NAME(WS-P) = L-NAME
                   MOVE "Y" TO WS-FOUND
                   SUBTRACT 1 FROM WS-P
               END-IF
           END-PERFORM.
           IF WS-FOUND = "N"
               IF WS-PROG-COUNT < 200 AND WS-USED + L-N <= 30000
                   ADD 1 TO WS-PROG-COUNT
                   MOVE WS-PROG-COUNT TO WS-P
                   MOVE L-NAME TO WS-PROG-NAME(WS-P)
                   MOVE WS-USED TO WS-PROG-BASE(WS-P)
                   MOVE L-N TO WS-PROG-N(WS-P)
                   ADD L-N TO WS-USED
                   PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > L-N
                       MOVE ZERO TO WS-HIT(WS-PROG-BASE(WS-P) + WS-I)
                   END-PERFORM
                   MOVE "Y" TO WS-FOUND
               END-IF
           END-IF.
           IF WS-FOUND = "Y"
               PERFORM VARYING WS-I FROM 1 BY 1
                   UNTIL WS-I > L-N OR WS-I > WS-PROG-N(WS-P)
                   ADD L-HIT(WS-I) TO WS-HIT(WS-PROG-BASE(WS-P) + WS-I)
                   MOVE ZERO TO L-HIT(WS-I)
               END-PERFORM
           END-IF.
       COV-READ.
           MOVE "E" TO L-OP.
           PERFORM UNTIL L-OP = "C" OR WS-CUR-P > WS-PROG-COUNT
               ADD 1 TO WS-CUR-I
               IF WS-CUR-I > WS-PROG-N(WS-CUR-P)
                   ADD 1 TO WS-CUR-P
                   MOVE ZERO TO WS-CUR-I
               ELSE
                   IF WS-HIT(WS-PROG-BASE(WS-CUR-P) + WS-CUR-I) > 0
                       MOVE "C" TO L-OP
                       MOVE WS-PROG-NAME(WS-CUR-P) TO L-NAME
                       MOVE WS-CUR-I TO L-N
                       MOVE WS-HIT(WS-PROG-BASE(WS-CUR-P) + WS-CUR-I)
                           TO L-HIT(1)
                   END-IF
               END-IF
           END-PERFORM.
       END PROGRAM CBLTCOV.
