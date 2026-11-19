       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOANCALC.
      * Sample subprogram: computes the monthly installment of a loan
      * under the French system (fixed installment), the total interest
      * and the first due date (one month after the start date,
      * adjusted to the last day of the month). It returns a return
      * code in LN-RETURN-CODE. All the data is made up.
      *
      * Note on dialects: the installment is computed in a single
      * COMPUTE with a division by the intermediate (WS-FACTOR - 1).
      * With -std=ibm, GnuCOBOL sets arithmetic-osvs ("limit precision
      * in intermediate results to precision of final result"), the
      * intermediate keeps the two decimals of LN-INSTALLMENT and the
      * installment changes. The TSTLOAN suite detects it.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MONTHLY-RATE           PIC 9V9(8).
       01  WS-FACTOR                 PIC 9(5)V9(12).
       01  WS-DATE.
           05  WS-DATE-NUM           PIC 9(8).
           05  WS-DATE-PARTS REDEFINES WS-DATE-NUM.
               10  WS-YEAR           PIC 9(4).
               10  WS-MONTH          PIC 9(2).
               10  WS-DAY            PIC 9(2).
       01  WS-DAYS-IN-MONTH          PIC 9(2).
       01  WS-MONTH-DAYS.
           05  FILLER                PIC X(24)
               VALUE "312831303130313130313031".
       01  WS-MONTH-TABLE REDEFINES WS-MONTH-DAYS.
           05  WS-MDAYS              PIC 9(2) OCCURS 12 TIMES.
       01  WS-REM-4                  PIC 9(4).
       01  WS-REM-100                PIC 9(4).
       01  WS-REM-400                PIC 9(4).
       01  WS-QUOTIENT               PIC 9(4).
       01  WS-LEAP                   PIC X VALUE "N".
           88  WS-LEAP-YEAR          VALUE "Y".
       LINKAGE SECTION.
       01  LN-LOAN.
           05  LN-PRINCIPAL          PIC 9(9)V99.
           05  LN-ANNUAL-RATE        PIC 9(2)V9(4).
           05  LN-TERM-MONTHS        PIC 9(3).
           05  LN-START-DATE         PIC 9(8).
           05  LN-INSTALLMENT        PIC 9(9)V99.
           05  LN-TOTAL-INTEREST     PIC S9(9)V99.
           05  LN-FIRST-DUE          PIC 9(8).
           05  LN-RETURN-CODE        PIC XX.
               88  LN-OK             VALUE "00".
               88  LN-BAD-PRINCIPAL  VALUE "10".
               88  LN-BAD-TERM       VALUE "20".
               88  LN-BAD-RATE       VALUE "30".
               88  LN-BAD-DATE       VALUE "40".
       PROCEDURE DIVISION USING LN-LOAN.
       0000-MAIN.
           PERFORM 1000-VALIDATE
           IF LN-OK
               PERFORM 2000-INSTALLMENT
               PERFORM 3000-FIRST-DUE
           END-IF
           EXIT PROGRAM.
       1000-VALIDATE.
           MOVE ZERO TO LN-INSTALLMENT LN-TOTAL-INTEREST LN-FIRST-DUE
           MOVE "00" TO LN-RETURN-CODE
           EVALUATE TRUE
               WHEN LN-PRINCIPAL = ZERO
                   MOVE "10" TO LN-RETURN-CODE
               WHEN LN-TERM-MONTHS < 1 OR LN-TERM-MONTHS > 360
                   MOVE "20" TO LN-RETURN-CODE
               WHEN LN-ANNUAL-RATE > 2
                   MOVE "30" TO LN-RETURN-CODE
               WHEN OTHER
                   PERFORM 1100-CHECK-DATE
           END-EVALUATE.
       1100-CHECK-DATE.
           MOVE LN-START-DATE TO WS-DATE-NUM
           PERFORM 1200-DAYS-IN-MONTH
           IF WS-DAYS-IN-MONTH = ZERO
              OR WS-DAY < 1 OR WS-DAY > WS-DAYS-IN-MONTH
               MOVE "40" TO LN-RETURN-CODE
           END-IF.
       1200-DAYS-IN-MONTH.
           IF WS-MONTH < 1 OR WS-MONTH > 12
               MOVE ZERO TO WS-DAYS-IN-MONTH
           ELSE
               MOVE WS-MDAYS(WS-MONTH) TO WS-DAYS-IN-MONTH
               IF WS-MONTH = 2
                   PERFORM 1300-LEAP-YEAR
                   IF WS-LEAP-YEAR
                       MOVE 29 TO WS-DAYS-IN-MONTH
                   END-IF
               END-IF
           END-IF.
       1300-LEAP-YEAR.
           DIVIDE WS-YEAR BY 4 GIVING WS-QUOTIENT REMAINDER WS-REM-4
           DIVIDE WS-YEAR BY 100 GIVING WS-QUOTIENT
               REMAINDER WS-REM-100
           DIVIDE WS-YEAR BY 400 GIVING WS-QUOTIENT
               REMAINDER WS-REM-400
           IF (WS-REM-4 = ZERO AND WS-REM-100 NOT = ZERO)
              OR WS-REM-400 = ZERO
               MOVE "Y" TO WS-LEAP
           ELSE
               MOVE "N" TO WS-LEAP
           END-IF.
       2000-INSTALLMENT.
           COMPUTE WS-MONTHLY-RATE ROUNDED = LN-ANNUAL-RATE / 12
           IF WS-MONTHLY-RATE = ZERO
               COMPUTE LN-INSTALLMENT ROUNDED =
                   LN-PRINCIPAL / LN-TERM-MONTHS
           ELSE
               MOVE 1 TO WS-FACTOR
               PERFORM LN-TERM-MONTHS TIMES
                   COMPUTE WS-FACTOR = WS-FACTOR * (1 + WS-MONTHLY-RATE)
               END-PERFORM
               COMPUTE LN-INSTALLMENT ROUNDED =
                   LN-PRINCIPAL * WS-MONTHLY-RATE * WS-FACTOR
                   / (WS-FACTOR - 1)
           END-IF
           COMPUTE LN-TOTAL-INTEREST =
               LN-INSTALLMENT * LN-TERM-MONTHS - LN-PRINCIPAL.
       3000-FIRST-DUE.
           MOVE LN-START-DATE TO WS-DATE-NUM
           ADD 1 TO WS-MONTH
           IF WS-MONTH > 12
               MOVE 1 TO WS-MONTH
               ADD 1 TO WS-YEAR
           END-IF
           PERFORM 1200-DAYS-IN-MONTH
           IF WS-DAY > WS-DAYS-IN-MONTH
               MOVE WS-DAYS-IN-MONTH TO WS-DAY
           END-IF
           MOVE WS-DATE-NUM TO LN-FIRST-DUE.
       END PROGRAM LOANCALC.
