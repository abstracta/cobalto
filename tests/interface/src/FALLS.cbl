       IDENTIFICATION DIVISION.
       PROGRAM-ID. FALLS.
      * Synthetic program: the main flow falls through from one
      * paragraph to the next without PERFORM. It pins the documented
      * limit of RUN, which executes only the entry paragraph.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STEP                   PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
       A-START.
           MOVE 1 TO WS-STEP.
       B-NEXT.
           MOVE 2 TO WS-STEP
           STOP RUN.
       END PROGRAM FALLS.
