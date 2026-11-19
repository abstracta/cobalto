       IDENTIFICATION DIVISION.
       PROGRAM-ID. LEGACY.
      * Synthetic "legacy style" program to exercise the in-program
      * rewriter: indexed file, READ with NOT INVALID KEY and a nested
      * IF without END-IF, dynamic CALL with ON EXCEPTION, IF/ELSE IF
      * closed only by the period, inline PERFORM, START, DELETE,
      * ACCEPT FROM TIME and COPY REPLACING. Made-up data.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OPTIONAL MASTER-FILE ASSIGN TO "build/master.dat"
               ORGANIZATION IS INDEXED ACCESS MODE IS DYNAMIC
               RECORD KEY IS M-KEY FILE STATUS IS WS-FS.
       DATA DIVISION.
       FILE SECTION.
       FD  MASTER-FILE.
       01  M-REC.
           COPY LEGCOPY REPLACING ==:TAG:== BY ==M==.
       WORKING-STORAGE SECTION.
       01  WS-FS                     PIC XX.
       01  WS-GRP.
           COPY LEGCOPY REPLACING ==:TAG:== BY ==WS==.
       01  WS-PROG                   PIC X(8) VALUE "NOSUCH".
       01  WS-B                      PIC 9(3).
       01  WS-TIME                   PIC X(8).
       01  WS-MSG                    PIC X(60) VALUE "hello, world. this
      -    " is not a final period".
       01  END-OF-FILE               PIC X VALUE "N".
       PROCEDURE DIVISION.
       MAIN.
           OPEN I-O MASTER-FILE.
           READ MASTER-FILE INTO WS-GRP
               INVALID KEY MOVE "Y" TO END-OF-FILE
               NOT INVALID KEY IF WS-KEY = "XXXX" MOVE 1 TO WS-B
                   ELSE MOVE 2 TO WS-B END-IF.
           IF WS-B = 1
               CALL WS-PROG USING WS-GRP ON EXCEPTION
                   DISPLAY "not found" NOT ON EXCEPTION ADD 1 TO WS-B
               END-CALL
           ELSE IF WS-B = 2 MOVE 3 TO WS-B ELSE MOVE 4 TO WS-B.
           EVALUATE WS-B
               WHEN 1 WRITE M-REC FROM WS-GRP INVALID KEY CONTINUE
               WHEN 2 REWRITE M-REC
                   INVALID KEY MOVE "E" TO WS-FS END-REWRITE
               WHEN OTHER PERFORM VARYING WS-B FROM 1 BY 1
                   UNTIL WS-B > 3
                   ACCEPT WS-TIME FROM TIME
               END-PERFORM
           END-EVALUATE.
           START MASTER-FILE KEY IS > M-KEY INVALID KEY GO TO EXIT-PARA.
           DELETE MASTER-FILE RECORD INVALID KEY DISPLAY "no record".
           CLOSE MASTER-FILE.
       EXIT-PARA.
           EXIT.
       END PROGRAM LEGACY.
