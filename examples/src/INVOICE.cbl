       IDENTIFICATION DIVISION.
       PROGRAM-ID. INVOICE.
      * Synthetic program under test (in-program mode): reads customers
      * from a sequential file, computes the net amount by calling
      * DISCOUNT and writes a report. All the data is made up.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUST-FILE ASSIGN TO "build/customers.dat"
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-CUST-STATUS.
           SELECT REPORT-FILE ASSIGN TO "build/invoice-report.dat"
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-REP-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  CUST-FILE.
       01  CUST-REC.
           05  CUST-ID               PIC X(4).
           05  CUST-NAME             PIC X(10).
           05  CUST-AMOUNT           PIC 9(7)V99.
       FD  REPORT-FILE.
       01  REPORT-REC                PIC X(80).
       WORKING-STORAGE SECTION.
       01  WS-CUST-STATUS            PIC XX.
       01  WS-REP-STATUS             PIC XX.
       01  WS-EOF                    PIC X VALUE "N".
           88  WS-END-OF-FILE        VALUE "Y".
       01  WS-CUST.
           05  WS-C-ID               PIC X(4).
           05  WS-C-NAME             PIC X(10).
           05  WS-C-AMOUNT           PIC 9(7)V99.
       01  WS-AMOUNT                 PIC 9(7)V99.
       01  WS-NET                    PIC 9(7)V99.
       01  WS-CATEGORY               PIC X(10).
       01  WS-TOTAL                  PIC 9(9)V99.
       01  WS-READ-COUNT             PIC 9(5).
       01  WS-LINE-COUNT             PIC 9(5).
       01  WS-DATE                   PIC 9(6).
       01  WS-LINE.
           05  WS-L-ID               PIC X(4).
           05  FILLER                PIC X VALUE SPACE.
           05  WS-L-NAME             PIC X(10).
           05  FILLER                PIC X VALUE SPACE.
           05  WS-L-NET              PIC Z(6)9.99.
           05  FILLER                PIC X VALUE SPACE.
           05  WS-L-CAT              PIC X(10).
           05  FILLER                PIC X(43) VALUE SPACES.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-INIT
           PERFORM 2000-PROCESS
           PERFORM 3000-END
           STOP RUN.
       1000-INIT.
           ACCEPT WS-DATE FROM DATE
           MOVE ZERO TO WS-TOTAL WS-READ-COUNT WS-LINE-COUNT
           MOVE "N" TO WS-EOF
           OPEN INPUT CUST-FILE
                OUTPUT REPORT-FILE
           PERFORM 2500-WRITE-HEADER.
       2000-PROCESS.
           PERFORM 2010-READ-CUST
           PERFORM UNTIL WS-END-OF-FILE
               PERFORM 2100-CALC
               PERFORM 2200-WRITE-LINE
               PERFORM 2010-READ-CUST
           END-PERFORM.
       2010-READ-CUST.
           READ CUST-FILE INTO WS-CUST
               AT END
                   SET WS-END-OF-FILE TO TRUE
               NOT AT END
                   ADD 1 TO WS-READ-COUNT
           END-READ.
       2100-CALC.
           MOVE WS-C-AMOUNT TO WS-AMOUNT
           CALL "DISCOUNT" USING WS-AMOUNT WS-NET WS-CATEGORY
           ADD WS-NET TO WS-TOTAL.
       2200-WRITE-LINE.
           MOVE WS-C-ID TO WS-L-ID
           MOVE WS-C-NAME TO WS-L-NAME
           MOVE WS-NET TO WS-L-NET
           MOVE WS-CATEGORY TO WS-L-CAT
           WRITE REPORT-REC FROM WS-LINE
           ADD 1 TO WS-LINE-COUNT.
       2500-WRITE-HEADER.
           MOVE SPACES TO REPORT-REC
           MOVE "INVOICING" TO REPORT-REC(1:11)
           MOVE WS-DATE TO REPORT-REC(13:6)
           WRITE REPORT-REC
           ADD 1 TO WS-LINE-COUNT.
       3000-END.
           CLOSE CUST-FILE REPORT-FILE.
       END PROGRAM INVOICE.
