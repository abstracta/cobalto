       IDENTIFICATION DIVISION.
       PROGRAM-ID. TSTCATEG.
      * Second test: categories only.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-AMOUNT                 PIC 9(7)V99.
       01  WS-RESULT                 PIC 9(7)V99.
       01  WS-CATEGORY               PIC X(10).
       LINKAGE SECTION.
       01  CBLT-CTX.
           COPY CBLTCTX.
       PROCEDURE DIVISION USING CBLT-CTX.
       MAIN.
           MOVE 500 TO WS-AMOUNT.
           CALL "DISCOUNT" USING WS-AMOUNT WS-RESULT WS-CATEGORY.
           MOVE "STANDARD" TO CBLT-EXP.
           MOVE WS-CATEGORY TO CBLT-ACT.
           CALL "CBLTEQ" USING CBLT-CTX.
           MOVE "PREMIUM" TO CBLT-EXP.
           CALL "CBLTNE" USING CBLT-CTX.
           EXIT PROGRAM.
       END PROGRAM TSTCATEG.
