       IDENTIFICATION DIVISION.
       PROGRAM-ID. PREMIUM.
      * Sample subprogram: annual premium of a life insurance policy
      * from a table of age bands (rate per mil, sequential SEARCH over
      * ranges) and a table of coverages sorted by code (percentage
      * loading, SEARCH ALL). It applies a minimum premium and returns
      * a return code in LN-RETURN-CODE. The rates and the data are
      * made up.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MIN-PREMIUM            PIC 9(5)V99 VALUE 50.00.
       01  WS-BASE-PREMIUM           PIC 9(9)V99.
       01  WS-AGE-BAND-VALUES.
           05  FILLER                PIC X(10) VALUE "0180300120".
           05  FILLER                PIC X(10) VALUE "0310400180".
           05  FILLER                PIC X(10) VALUE "0410500290".
           05  FILLER                PIC X(10) VALUE "0510600470".
           05  FILLER                PIC X(10) VALUE "0610700830".
           05  FILLER                PIC X(10) VALUE "0710801450".
       01  WS-AGE-BANDS REDEFINES WS-AGE-BAND-VALUES.
           05  WS-BAND OCCURS 6 TIMES INDEXED BY BAND-IDX.
               10  WS-BAND-FROM      PIC 9(3).
               10  WS-BAND-TO        PIC 9(3).
               10  WS-BAND-RATE      PIC 9(2)V99.
       01  WS-COVERAGE-VALUES.
           05  FILLER                PIC X(8) VALUE "BAS00000".
           05  FILLER                PIC X(8) VALUE "FUL03500".
           05  FILLER                PIC X(8) VALUE "STD01500".
       01  WS-COVERAGES REDEFINES WS-COVERAGE-VALUES.
           05  WS-COVERAGE OCCURS 3 TIMES
               ASCENDING KEY IS WS-COV-CODE
               INDEXED BY COV-IDX.
               10  WS-COV-CODE       PIC X(3).
               10  WS-COV-LOADING    PIC 9(3)V99.
       LINKAGE SECTION.
       01  LN-QUOTE.
           05  LN-AGE                PIC 9(3).
           05  LN-COVERAGE           PIC X(3).
           05  LN-SUM-INSURED        PIC 9(9)V99.
           05  LN-RATE-PER-MIL       PIC 9(2)V99.
           05  LN-LOADING-PCT        PIC 9(3)V99.
           05  LN-PREMIUM            PIC 9(9)V99.
           05  LN-RETURN-CODE        PIC XX.
               88  LN-OK             VALUE "00".
               88  LN-AGE-NOT-COVERED VALUE "10".
               88  LN-UNKNOWN-COVERAGE VALUE "20".
               88  LN-NO-SUM-INSURED VALUE "30".
       PROCEDURE DIVISION USING LN-QUOTE.
       0000-MAIN.
           MOVE ZERO TO LN-RATE-PER-MIL LN-LOADING-PCT LN-PREMIUM
           MOVE "00" TO LN-RETURN-CODE
           IF LN-SUM-INSURED = ZERO
               MOVE "30" TO LN-RETURN-CODE
           ELSE
               PERFORM 1000-FIND-AGE-BAND
           END-IF
           IF LN-OK
               PERFORM 2000-FIND-COVERAGE
           END-IF
           IF LN-OK
               PERFORM 3000-COMPUTE-PREMIUM
           END-IF
           EXIT PROGRAM.
       1000-FIND-AGE-BAND.
           SET BAND-IDX TO 1
           SEARCH WS-BAND
               AT END
                   MOVE "10" TO LN-RETURN-CODE
               WHEN LN-AGE >= WS-BAND-FROM(BAND-IDX)
                    AND LN-AGE <= WS-BAND-TO(BAND-IDX)
                   MOVE WS-BAND-RATE(BAND-IDX) TO LN-RATE-PER-MIL
           END-SEARCH.
       2000-FIND-COVERAGE.
           SEARCH ALL WS-COVERAGE
               AT END
                   MOVE "20" TO LN-RETURN-CODE
               WHEN WS-COV-CODE(COV-IDX) = LN-COVERAGE
                   MOVE WS-COV-LOADING(COV-IDX) TO LN-LOADING-PCT
           END-SEARCH.
       3000-COMPUTE-PREMIUM.
           COMPUTE WS-BASE-PREMIUM ROUNDED =
               LN-SUM-INSURED * LN-RATE-PER-MIL / 1000
           COMPUTE LN-PREMIUM ROUNDED = WS-BASE-PREMIUM
               + WS-BASE-PREMIUM * LN-LOADING-PCT / 100
           IF LN-PREMIUM < WS-MIN-PREMIUM
               MOVE WS-MIN-PREMIUM TO LN-PREMIUM
           END-IF.
       END PROGRAM PREMIUM.
