       IDENTIFICATION DIVISION.
       PROGRAM-ID. DISCOUNT.
      * Program under test: applies a discount based on the amount.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RATE                   PIC 9V99.
       LINKAGE SECTION.
       01  LN-AMOUNT                 PIC 9(7)V99.
       01  LN-RESULT                 PIC 9(7)V99.
       01  LN-CATEGORY               PIC X(10).
       PROCEDURE DIVISION USING LN-AMOUNT LN-RESULT LN-CATEGORY.
       MAIN.
           EVALUATE TRUE
               WHEN LN-AMOUNT >= 1000
                   MOVE 0.20 TO WS-RATE
                   MOVE "PREMIUM" TO LN-CATEGORY
               WHEN LN-AMOUNT >= 500
                   MOVE 0.10 TO WS-RATE
                   MOVE "STANDARD" TO LN-CATEGORY
               WHEN OTHER
                   MOVE 0.00 TO WS-RATE
                   MOVE "BASIC" TO LN-CATEGORY
           END-EVALUATE.
           COMPUTE LN-RESULT = LN-AMOUNT - (LN-AMOUNT * WS-RATE).
           EXIT PROGRAM.
       END PROGRAM DISCOUNT.
