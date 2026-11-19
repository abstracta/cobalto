       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECTS.
      * Synthetic program for the interface test regression suite:
      * the entry is a SECTION, a STOP RUN inside an IF at the start
      * of the flow is followed by multi-line statements with
      * conditional phrases (READ, inline PERFORM) and by a READ that
      * a test case simulates; another SECTION has two paragraphs
      * (fall-through) and a GOBACK inside an IF. No business meaning.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO "build/sects-in.dat"
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-IN-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC                    PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-IN-STATUS              PIC XX.
       01  WS-MODE                   PIC X VALUE "A".
       01  WS-STEP                   PIC 9(3) VALUE 0.
       01  WS-COUNT                  PIC 9(3) VALUE 0.
       01  WS-EOF                    PIC X VALUE "N".
       01  WS-TRACE                  PIC X(30) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN SECTION.
       0000-START.
           MOVE 1 TO WS-STEP
           OPEN INPUT IN-FILE
           IF WS-IN-STATUS NOT = "00"
               MOVE "OPEN FAILED" TO WS-TRACE
               STOP RUN
           END-IF
           READ IN-FILE
               AT END
                   MOVE "Y" TO WS-EOF
               NOT AT END
                   ADD 1 TO WS-COUNT
           END-READ
           PERFORM
               UNTIL WS-EOF = "Y"
               READ IN-FILE
                   AT END MOVE "Y" TO WS-EOF
                   NOT AT END ADD 1 TO WS-COUNT
               END-READ
           END-PERFORM
           MOVE
               2 TO WS-STEP
           PERFORM WORK-PART
           MOVE 3 TO WS-STEP
           CLOSE IN-FILE
           STOP RUN.
       WORK-PART SECTION.
       1000-CHECK.
           IF WS-MODE = "G"
               MOVE "GOBACK IN SECTION" TO WS-TRACE
               GOBACK
           END-IF.
           MOVE "DETAIL DONE" TO WS-TRACE.
       1100-TAIL.
           MOVE 9 TO WS-STEP.
       END PROGRAM SECTS.
