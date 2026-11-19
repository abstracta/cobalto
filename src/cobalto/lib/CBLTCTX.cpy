      *----------------------------------------------------------------
      * Cobalto (CBLT) - Context shared by the driver, the tests and the
      * asserts. Standard COBOL 85. The COPY user declares the 01:
      *     01  CBLT-CTX.
      *         COPY CBLTCTX.
      *----------------------------------------------------------------
           05  CBLT-TEST-NAME        PIC X(30).
           05  CBLT-ASSERT-COUNT     PIC 9(5).
           05  CBLT-FAIL-COUNT       PIC 9(5).
           05  CBLT-MSG              PIC X(60).
           05  CBLT-EXP              PIC X(256).
           05  CBLT-ACT              PIC X(256).
           05  CBLT-EXP-NUM          PIC S9(15)V9(3).
           05  CBLT-ACT-NUM          PIC S9(15)V9(3).
           05  CBLT-EXP-NUM2         PIC S9(15)V9(3).
           05  CBLT-LOG-COUNT        PIC 9(3).
           05  CBLT-LOG OCCURS 500 TIMES.
               10  CBLT-LOG-STATUS   PIC X.
               10  CBLT-LOG-NR       PIC 9(5).
               10  CBLT-LOG-KIND     PIC X(8).
               10  CBLT-LOG-EXP      PIC X(60).
               10  CBLT-LOG-ACT      PIC X(60).
               10  CBLT-LOG-MSG      PIC X(60).
