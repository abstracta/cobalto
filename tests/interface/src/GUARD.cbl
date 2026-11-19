       IDENTIFICATION DIVISION.
       PROGRAM-ID. GUARD.
      * Synthetic program for the interface test regression suite:
      * STOP RUN in the middle of the main paragraph (inside an IF) and
      * GOBACK inside an IF in an inner paragraph. No business
      * meaning; it exists to test the guards that the rewriter
      * places after a STOP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MODE                   PIC X VALUE "A".
       01  WS-STEP                   PIC 9(3) VALUE 0.
       01  WS-TRACE                  PIC X(20) VALUE SPACES.
       PROCEDURE DIVISION.
       0000-MAIN.
           MOVE 1 TO WS-STEP
           IF WS-MODE = "X"
               MOVE "ABORT" TO WS-TRACE
               STOP RUN
           END-IF
           MOVE 2 TO WS-STEP
           PERFORM 1000-WORK
           MOVE 3 TO WS-STEP.
           MOVE 4 TO WS-STEP
           STOP RUN.
       1000-WORK.
           IF WS-MODE = "G"
               MOVE "GOBACK" TO WS-TRACE
               GOBACK
           END-IF
           MOVE "WORKED" TO WS-TRACE.
       END PROGRAM GUARD.
