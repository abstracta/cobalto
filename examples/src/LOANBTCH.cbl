       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOANBTCH.
      * Sample batch: monthly settlement of loans. It reads the loan
      * master file, computes the installment of each active loan by
      * calling LOANCALC, writes the debit transactions to one file and
      * the rejects to another, and ends with a control record. All the
      * data is made up.
      *
      * Defect seeded on purpose (see tests/LOANBTCH.cblt, test case
      * "the control record counts only the transactions"): the counter
      * WS-LINE-COUNT also counts the header, and it is the one reported
      * in the control record as the number of transactions.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT LOAN-FILE ASSIGN TO "build/loans.dat"
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-LOAN-STATUS.
           SELECT DEBIT-FILE ASSIGN TO "build/debits.dat"
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-DEBIT-STATUS.
           SELECT REJECT-FILE ASSIGN TO "build/rejects.dat"
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-REJECT-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  LOAN-FILE.
       01  LOAN-REC.
           05  LOAN-ID               PIC X(8).
           05  LOAN-CUSTOMER         PIC X(10).
           05  LOAN-PRINCIPAL        PIC 9(9)V99.
           05  LOAN-ANNUAL-RATE      PIC 9(2)V9(4).
           05  LOAN-TERM-MONTHS      PIC 9(3).
           05  LOAN-START-DATE       PIC 9(8).
           05  LOAN-STATUS           PIC X.
       FD  DEBIT-FILE.
       01  DEBIT-REC                 PIC X(60).
       FD  REJECT-FILE.
       01  REJECT-REC                PIC X(60).
       WORKING-STORAGE SECTION.
       01  WS-LOAN-STATUS            PIC XX.
       01  WS-DEBIT-STATUS           PIC XX.
       01  WS-REJECT-STATUS          PIC XX.
       01  WS-EOF                    PIC X VALUE "N".
           88  WS-END-OF-FILE        VALUE "Y".
       01  WS-PROCESS-DATE           PIC 9(6).
       01  WS-READ-COUNT             PIC 9(5).
       01  WS-DEBIT-COUNT            PIC 9(5).
       01  WS-REJECT-COUNT           PIC 9(5).
       01  WS-SKIP-COUNT             PIC 9(5).
       01  WS-LINE-COUNT             PIC 9(5).
       01  WS-TOTAL-DEBIT            PIC S9(11)V99.
       01  WS-LOAN.
           05  WS-L-PRINCIPAL        PIC 9(9)V99.
           05  WS-L-ANNUAL-RATE      PIC 9(2)V9(4).
           05  WS-L-TERM-MONTHS      PIC 9(3).
           05  WS-L-START-DATE       PIC 9(8).
           05  WS-L-INSTALLMENT      PIC 9(9)V99.
           05  WS-L-TOTAL-INTEREST   PIC S9(9)V99.
           05  WS-L-FIRST-DUE        PIC 9(8).
           05  WS-L-RETURN-CODE      PIC XX.
               88  WS-L-OK           VALUE "00".
       01  WS-DEBIT-LINE.
           05  WS-D-ID               PIC X(8).
           05  FILLER                PIC X VALUE SPACE.
           05  WS-D-CUSTOMER         PIC X(10).
           05  FILLER                PIC X VALUE SPACE.
           05  WS-D-INSTALLMENT      PIC Z(8)9.99.
           05  FILLER                PIC X VALUE SPACE.
           05  WS-D-DUE-DATE         PIC 9(8).
           05  FILLER                PIC X VALUE SPACE.
           05  WS-D-TEXT             PIC X(17) VALUE "INSTALLMENT".
       01  WS-REJECT-LINE.
           05  WS-R-ID               PIC X(8).
           05  FILLER                PIC X VALUE SPACE.
           05  WS-R-CODE             PIC XX.
           05  FILLER                PIC X VALUE SPACE.
           05  WS-R-TEXT             PIC X(47).
       01  WS-TRAILER.
           05  FILLER                PIC X(8) VALUE "CONTROL ".
           05  WS-T-COUNT            PIC 9(5).
           05  FILLER                PIC X VALUE SPACE.
           05  WS-T-TOTAL            PIC Z(10)9.99.
           05  FILLER                PIC X(32) VALUE SPACES.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-INIT
           PERFORM 2000-PROCESS
           PERFORM 3000-END
           STOP RUN.
       1000-INIT.
           ACCEPT WS-PROCESS-DATE FROM DATE
           MOVE ZERO TO WS-READ-COUNT WS-DEBIT-COUNT WS-REJECT-COUNT
                        WS-SKIP-COUNT WS-LINE-COUNT WS-TOTAL-DEBIT
           MOVE "N" TO WS-EOF
           OPEN INPUT LOAN-FILE
                OUTPUT DEBIT-FILE REJECT-FILE
           PERFORM 2500-WRITE-HEADER.
       2000-PROCESS.
           PERFORM 2010-READ-LOAN
           PERFORM UNTIL WS-END-OF-FILE
               PERFORM 2100-PROCESS-LOAN
               PERFORM 2010-READ-LOAN
           END-PERFORM.
       2010-READ-LOAN.
           READ LOAN-FILE
               AT END
                   SET WS-END-OF-FILE TO TRUE
               NOT AT END
                   ADD 1 TO WS-READ-COUNT
           END-READ.
       2100-PROCESS-LOAN.
           IF LOAN-STATUS NOT = "A"
               ADD 1 TO WS-SKIP-COUNT
           ELSE
               MOVE LOAN-PRINCIPAL TO WS-L-PRINCIPAL
               MOVE LOAN-ANNUAL-RATE TO WS-L-ANNUAL-RATE
               MOVE LOAN-TERM-MONTHS TO WS-L-TERM-MONTHS
               MOVE LOAN-START-DATE TO WS-L-START-DATE
               CALL "LOANCALC" USING WS-LOAN
               IF WS-L-OK
                   PERFORM 2200-WRITE-DEBIT
               ELSE
                   PERFORM 2300-WRITE-REJECT
               END-IF
           END-IF.
       2200-WRITE-DEBIT.
           MOVE LOAN-ID TO WS-D-ID
           MOVE LOAN-CUSTOMER TO WS-D-CUSTOMER
           MOVE WS-L-INSTALLMENT TO WS-D-INSTALLMENT
           MOVE WS-L-FIRST-DUE TO WS-D-DUE-DATE
           WRITE DEBIT-REC FROM WS-DEBIT-LINE
           ADD WS-L-INSTALLMENT TO WS-TOTAL-DEBIT
           ADD 1 TO WS-DEBIT-COUNT
           ADD 1 TO WS-LINE-COUNT.
       2300-WRITE-REJECT.
           MOVE LOAN-ID TO WS-R-ID
           MOVE WS-L-RETURN-CODE TO WS-R-CODE
           EVALUATE WS-L-RETURN-CODE
               WHEN "10" MOVE "ZERO PRINCIPAL" TO WS-R-TEXT
               WHEN "20" MOVE "TERM OUT OF RANGE" TO WS-R-TEXT
               WHEN "30" MOVE "RATE OUT OF RANGE" TO WS-R-TEXT
               WHEN "40" MOVE "INVALID START DATE"
                   TO WS-R-TEXT
               WHEN OTHER MOVE "UNCATALOGED ERROR" TO WS-R-TEXT
           END-EVALUATE
           WRITE REJECT-REC FROM WS-REJECT-LINE
           ADD 1 TO WS-REJECT-COUNT.
       2500-WRITE-HEADER.
           MOVE SPACES TO DEBIT-REC
           MOVE "SETTLEMENT" TO DEBIT-REC(1:11)
      * system date as YYMMDD (COBOL 85) with the century fixed at 20,
      * like so many programs that got past 2000 with a window
           MOVE "20" TO DEBIT-REC(13:2)
           MOVE WS-PROCESS-DATE TO DEBIT-REC(15:6)
           WRITE DEBIT-REC
           ADD 1 TO WS-LINE-COUNT.
       2600-WRITE-TRAILER.
           MOVE WS-LINE-COUNT TO WS-T-COUNT
           MOVE WS-TOTAL-DEBIT TO WS-T-TOTAL
           WRITE DEBIT-REC FROM WS-TRAILER.
       3000-END.
           PERFORM 2600-WRITE-TRAILER
           CLOSE LOAN-FILE DEBIT-FILE REJECT-FILE.
       END PROGRAM LOANBTCH.
