       IDENTIFICATION DIVISION.
       PROGRAM-ID. DAYCLOSE.
      * Sample program in "legacy style": the daily close of an account.
      * It walks the table of movements of the day with a long
      * paragraph written the way it was done thirty years ago (GO TO,
      * nested IFs closed by the period, flags), adds up debits and
      * credits, rejects the invalid movements and builds a control
      * record with COMP fields. All the data is made up.
      *
      * Some results change when it is compiled with another dialect:
      *  - WS-MOV-COUNT is PIC 9(4) COMP and carries over from the
      *    previous day. With -std=default (binary-truncate: yes) it
      *    keeps the four digits of the PIC (9999 + 3 = 0002); with
      *    -std=ibm or -std=mf (binary-truncate: no) it holds 10002.
      *  - WS-CONTROL is 11 bytes long with -std=default (binary-size
      *    1-2-4-8), 12 with -std=ibm (2-4-8: no COMP takes one byte)
      *    and 9 with -std=mf (1--8: the fewest bytes that are enough).
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ATM-LIMIT              PIC 9(7)V99 VALUE 50000.00.
       01  WS-OPENING-BALANCE        PIC S9(11)V99.
       01  WS-NET-BALANCE            PIC S9(11)V99.
       01  WS-TOTAL-DEBITS           PIC S9(11)V99 COMP.
       01  WS-TOTAL-CREDITS          PIC S9(11)V99 COMP.
       01  WS-MOV-COUNT              PIC 9(4) COMP.
       01  WS-REJECTS                PIC 9(2) COMP.
       01  WS-I                      PIC 9(3).
       01  WS-MOV-TOTAL              PIC 9(3).
       01  WS-MOVEMENTS.
           05  WS-MOV OCCURS 50 TIMES.
               10  WS-MOV-TYPE       PIC X.
               10  WS-MOV-CHANNEL    PIC X(3).
               10  WS-MOV-AMOUNT     PIC 9(9)V99.
               10  WS-MOV-STATUS     PIC X.
       01  WS-CONTROL.
           05  WS-CTL-REJECTS        PIC 9(2) COMP.
           05  WS-CTL-COUNT          PIC 9(4) COMP.
           05  WS-CTL-TOTAL          PIC S9(11)V99 COMP.
       01  WS-CTL-LEN                PIC 9(3).
       01  WS-CTL-FLAG               PIC X(9).
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM CLOSE-DAY THRU CLOSE-EXIT
           STOP RUN.
       CLOSE-DAY.
           MOVE ZERO TO WS-TOTAL-DEBITS WS-TOTAL-CREDITS WS-REJECTS
                        WS-I.
       CLOSE-LOOP.
           ADD 1 TO WS-I.
           IF WS-I > WS-MOV-TOTAL GO TO CLOSE-TRAILER.
           IF WS-MOV-AMOUNT(WS-I) = ZERO
               ADD 1 TO WS-REJECTS
               MOVE "Z" TO WS-MOV-STATUS(WS-I)
               GO TO CLOSE-LOOP.
           IF WS-MOV-TYPE(WS-I) = "D"
               IF WS-MOV-CHANNEL(WS-I) = "ATM"
                  AND WS-MOV-AMOUNT(WS-I) > WS-ATM-LIMIT
                   ADD 1 TO WS-REJECTS
                   MOVE "L" TO WS-MOV-STATUS(WS-I)
               ELSE
                   ADD WS-MOV-AMOUNT(WS-I) TO WS-TOTAL-DEBITS
                   MOVE "P" TO WS-MOV-STATUS(WS-I)
           ELSE
               IF WS-MOV-TYPE(WS-I) = "C"
                   ADD WS-MOV-AMOUNT(WS-I) TO WS-TOTAL-CREDITS
                   MOVE "P" TO WS-MOV-STATUS(WS-I)
               ELSE
                   ADD 1 TO WS-REJECTS
                   MOVE "T" TO WS-MOV-STATUS(WS-I).
           IF WS-MOV-STATUS(WS-I) = "P" ADD 1 TO WS-MOV-COUNT.
           GO TO CLOSE-LOOP.
       CLOSE-TRAILER.
           COMPUTE WS-NET-BALANCE = WS-OPENING-BALANCE
               + WS-TOTAL-CREDITS - WS-TOTAL-DEBITS.
           MOVE WS-REJECTS TO WS-CTL-REJECTS.
           MOVE WS-MOV-COUNT TO WS-CTL-COUNT.
           MOVE WS-NET-BALANCE TO WS-CTL-TOTAL.
           COMPUTE WS-CTL-LEN = FUNCTION LENGTH(WS-CONTROL).
           IF WS-NET-BALANCE < ZERO
               MOVE "OVERDRAWN" TO WS-CTL-FLAG
           ELSE
               MOVE "OK" TO WS-CTL-FLAG.
       CLOSE-EXIT.
           EXIT.
       END PROGRAM DAYCLOSE.
