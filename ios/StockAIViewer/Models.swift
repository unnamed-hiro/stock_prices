// Models.swift — リポジトリが蓄積する JSON のデータモデル
// (data/state/portfolio.json / results/daily/*.json / results/monthly/*.json)

import Foundation

// MARK: - 口座状態 (data/state/portfolio.json)

struct PortfolioState: Decodable {
    let initialCapital: Double
    let cash: Double
    let positions: [String: Position]
    let trades: [TradeRecord]
    let equityCurve: [EquityPoint]
    let totalDeposits: Double

    enum CodingKeys: String, CodingKey {
        case initialCapital = "initial_capital"
        case cash, positions, trades
        case equityCurve = "equity_curve"
        case totalDeposits = "total_deposits"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        initialCapital = try c.decode(Double.self, forKey: .initialCapital)
        cash = try c.decode(Double.self, forKey: .cash)
        positions = try c.decode([String: Position].self, forKey: .positions)
        trades = try c.decode([TradeRecord].self, forKey: .trades)
        totalDeposits = try c.decodeIfPresent(Double.self, forKey: .totalDeposits) ?? 0
        // equity_curve は [["2026-07-03 00:00:00", 5207737.0], ...] 形式
        let raw = try c.decode([[RawPoint]].self, forKey: .equityCurve)
        equityCurve = raw.compactMap { pair in
            guard pair.count == 2,
                  case .string(let d) = pair[0],
                  case .number(let v) = pair[1],
                  v.isFinite,
                  let date = Self.parseDate(d) else { return nil }
            return EquityPoint(date: date, value: v)
        }
    }

    var investedCapital: Double { initialCapital + totalDeposits }
    var currentEquity: Double { equityCurve.last?.value ?? cash }
    var returnPct: Double {
        investedCapital > 0 ? (currentEquity - investedCapital) / investedCapital * 100 : 0
    }

    enum RawPoint: Decodable {
        case string(String)
        case number(Double)
        case null
        init(from decoder: Decoder) throws {
            let c = try decoder.singleValueContainer()
            if c.decodeNil() { self = .null; return }
            if let s = try? c.decode(String.self) { self = .string(s); return }
            self = .number(try c.decode(Double.self))
        }
    }

    static func parseDate(_ s: String) -> Date? {
        let fmts = ["yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd"]
        for f in fmts {
            let df = DateFormatter()
            df.locale = Locale(identifier: "en_US_POSIX")
            df.dateFormat = f
            if let d = df.date(from: s) { return d }
        }
        return nil
    }
}

struct EquityPoint: Identifiable {
    var id: Date { date }
    let date: Date
    let value: Double
}

struct Position: Decodable, Identifiable {
    let ticker: String
    let shares: Int
    let entryPrice: Double
    let entryDate: String
    var id: String { ticker }

    enum CodingKeys: String, CodingKey {
        case ticker, shares
        case entryPrice = "entry_price"
        case entryDate = "entry_date"
    }
}

struct TradeRecord: Decodable {
    let ticker: String
    let side: String
    let shares: Int
    let price: Double
    let date: String
    let pnl: Double
}

// MARK: - 日次レポート (results/daily/YYYY-MM-DD.json)

struct DailyReport: Decodable, Identifiable {
    let date: String
    let strategy: String
    let startingEquity: Double
    let endingEquity: Double
    let cash: Double
    let nPositions: Int
    let regime: String?
    let exits: [JSONDict]
    let executedBuys: [JSONDict]
    let executedSells: [JSONDict]
    let skipped: [JSONDict]
    let plannedOrders: [JSONDict]
    var id: String { date }

    enum CodingKeys: String, CodingKey {
        case date, strategy, cash, regime, exits, skipped
        case startingEquity = "starting_equity"
        case endingEquity = "ending_equity"
        case nPositions = "n_positions"
        case executedBuys = "executed_buys"
        case executedSells = "executed_sells"
        case plannedOrders = "planned_orders"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        date = try c.decode(String.self, forKey: .date)
        strategy = try c.decode(String.self, forKey: .strategy)
        startingEquity = (try? c.decode(Double.self, forKey: .startingEquity)) ?? 0
        endingEquity = (try? c.decode(Double.self, forKey: .endingEquity)) ?? 0
        cash = try c.decode(Double.self, forKey: .cash)
        nPositions = try c.decode(Int.self, forKey: .nPositions)
        regime = try c.decodeIfPresent(String.self, forKey: .regime)
        exits = try c.decodeIfPresent([JSONDict].self, forKey: .exits) ?? []
        executedBuys = try c.decodeIfPresent([JSONDict].self, forKey: .executedBuys) ?? []
        executedSells = try c.decodeIfPresent([JSONDict].self, forKey: .executedSells) ?? []
        skipped = try c.decodeIfPresent([JSONDict].self, forKey: .skipped) ?? []
        plannedOrders = try c.decodeIfPresent([JSONDict].self, forKey: .plannedOrders) ?? []
    }
}

// MARK: - 月次レポート (results/monthly/YYYY-MM.json)

struct MonthlyReport: Decodable, Identifiable {
    let month: String
    let equityStart: Double
    let equityEnd: Double
    let depositsInMonth: Double
    let profit: Double
    let monthReturnPct: Double
    let cumulativeReturnPct: Double
    let benchmarkPct: Double?
    let alphaPct: Double?
    let nClosed: Int
    let winRatePct: Double?
    let payoffRatio: Double?
    let riskOffDays: Int
    let earningsSkips: Int
    let tradingDays: Int
    var id: String { month }

    enum CodingKeys: String, CodingKey {
        case month, profit
        case equityStart = "equity_start"
        case equityEnd = "equity_end"
        case depositsInMonth = "deposits_in_month"
        case monthReturnPct = "month_return_pct"
        case cumulativeReturnPct = "cumulative_return_pct"
        case benchmarkPct = "benchmark_pct"
        case alphaPct = "alpha_pct"
        case nClosed = "n_closed"
        case winRatePct = "win_rate_pct"
        case payoffRatio = "payoff_ratio"
        case riskOffDays = "risk_off_days"
        case earningsSkips = "earnings_skips"
        case tradingDays = "trading_days"
    }
}

// MARK: - 実弾移行判定 (results/readiness.json)

struct Readiness: Decodable {
    let ready: Bool
    let criteria: [Criterion]
    let verdict: String
    let note: String?

    struct Criterion: Decodable, Identifiable {
        let name: String
        let status: String   // "pass" | "pending" | "fail"
        let detail: String
        var id: String { name }
        var icon: String {
            switch status {
            case "pass": return "checkmark.circle.fill"
            case "fail": return "xmark.circle.fill"
            default: return "hourglass.circle"
            }
        }
    }
}

// MARK: - 汎用辞書 (exits / skipped などスキーマが緩い配列要素用)

struct JSONDict: Decodable, Identifiable {
    let values: [String: String]
    let id = UUID()

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        var out: [String: String] = [:]
        for key in c.allKeys {
            if let s = try? c.decode(String.self, forKey: key) {
                out[key.stringValue] = s
            } else if let d = try? c.decode(Double.self, forKey: key) {
                out[key.stringValue] = d == d.rounded()
                    ? String(format: "%.0f", d) : String(format: "%.2f", d)
            } else if let b = try? c.decode(Bool.self, forKey: key) {
                out[key.stringValue] = b ? "true" : "false"
            }
        }
        values = out
    }

    subscript(_ key: String) -> String { values[key] ?? "" }

    struct AnyKey: CodingKey {
        var stringValue: String
        var intValue: Int? { nil }
        init?(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { return nil }
    }
}

// MARK: - 表示ヘルパー

func yen(_ v: Double) -> String {
    let f = NumberFormatter()
    f.numberStyle = .decimal
    f.maximumFractionDigits = 0
    return (f.string(from: NSNumber(value: v)) ?? "0") + "円"
}

func pct(_ v: Double?) -> String {
    guard let v else { return "—" }
    return String(format: "%+.2f%%", v)
}
