// Every number the landing shows about the demo borrower, taken from the mock export of the
// live database (public/mock/*.json). content.test.ts recomputes each one from the mocks, so
// the copy can never drift from the data.

export const AARAV = {
  name: "Aarav S.",
  income: 48000,
  score: 742,
  age: 29,
  matches: 39,
  eligible: 9,
  lenders: 26,
  bestRate: 9.5,
} as const;

/** Slide 2: each lender's best platform, ranked by fit score then rate. */
export const RANKED: ReadonlyArray<{ lender: string; via: string; rate: number; fit: number; verified: boolean }> = [
  { lender: "Axis Bank", via: "via BankBazaar", rate: 9.5, fit: 90.2, verified: true },
  { lender: "IDFC FIRST Bank", via: "direct", rate: 9.99, fit: 82.5, verified: false },
  { lender: "IndusInd Bank", via: "via Paisabazaar", rate: 10.5, fit: 82.3, verified: true },
  { lender: "IDBI Bank", via: "via BankBazaar", rate: 11.0, fit: 82.0, verified: false },
  { lender: "Federal Bank", via: "via Paisabazaar", rate: 12.0, fit: 81.5, verified: false },
];

/** Slide 3: the top match's fit score, part by part (Axis Bank via BankBazaar). */
export const TOP_FIT = { minIncome: 15000, incomeMultiple: 3.2, rate: 9.5, parts: [60, 15, 5, 10.2], total: 90.2 } as const;

/** Slide 4: the compare example, at each lender's starting rate. */
export const COMPARE = {
  principal: 500000,
  months: 36,
  lenders: [
    { lender: "Axis Bank", rate: 9.5 },
    { lender: "IndusInd Bank", rate: 10.5 },
    { lender: "YES Bank", rate: 10.85 },
  ],
} as const;

/** Slide 5: the runner-up rows in the email (lender, platform, rate, fit). */
export const EMAIL_ROWS = [
  { lender: "IndusInd Bank", via: "via Paisabazaar", rate: 10.5, fit: 82.3 },
  { lender: "YES Bank", via: "via BankBazaar", rate: 10.85, fit: 81.3 },
] as const;

/** The 26 lenders in the catalog, for the ticker, by display name. */
export const LENDERS: readonly string[] = [
  "Axis Bank", "Bank of Baroda", "Bank of India", "Bank of Maharashtra", "Canara Bank", "Central Bank of India",
  "Federal Bank", "HDB Financial Services", "HDFC Bank", "ICICI Bank", "IDBI Bank", "IDFC FIRST Bank",
  "IIFL Finance", "Indian Bank", "IndusInd Bank", "Kotak Mahindra Bank", "Punjab & Sind Bank",
  "Punjab National Bank", "RBL Bank", "SBI", "Standard Chartered", "Tata Capital", "UCO Bank", "Ujjivan",
  "Union Bank of India", "YES Bank",
];

/** Catalog spelling -> display spelling, for the lenders whose stored name is not the brand. */
export const DISPLAY_NAME: Readonly<Record<string, string>> = {
  Idbi: "IDBI Bank",
  Uco: "UCO Bank",
  "Union Bank": "Union Bank of India",
  "Bank Of India": "Bank of India",
  "Bank Of Maharashtra": "Bank of Maharashtra",
  "Central Bank Of India": "Central Bank of India",
  "Punjab And Sind Bank": "Punjab & Sind Bank",
};

/** The brand name for a catalog lender. */
export const displayName = (lender: string): string => DISPLAY_NAME[lender] ?? lender;
