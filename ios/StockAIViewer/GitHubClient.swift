// GitHubClient.swift — リポジトリの JSON を GitHub Contents API から取得
//
// プライベートリポジトリでも Fine-grained PAT (Contents: Read-only) を
// 設定すれば読める。パブリックならトークン不要。

import Foundation

enum GitHubError: LocalizedError {
    case badURL
    case http(Int)
    case decode(String)

    var errorDescription: String? {
        switch self {
        case .badURL: return "URLが不正です (設定を確認)"
        case .http(let code):
            if code == 404 { return "ファイルが見つかりません (404)。リポジトリ名/トークンを確認" }
            if code == 401 || code == 403 { return "認証エラー (\(code))。トークンを確認" }
            return "HTTPエラー \(code)"
        case .decode(let msg): return "データ解析エラー: \(msg)"
        }
    }
}

struct RepoFile: Decodable, Identifiable {
    let name: String
    let path: String
    var id: String { path }
}

final class GitHubClient {
    let owner: String
    let repo: String
    let branch: String
    let token: String

    init() {
        let d = UserDefaults.standard
        owner = d.string(forKey: "gh_owner") ?? "unnamed-hiro"
        repo = d.string(forKey: "gh_repo") ?? "stock_prices"
        branch = d.string(forKey: "gh_branch") ?? "main"
        token = d.string(forKey: "github_token") ?? ""
    }

    private func request(_ path: String, raw: Bool) throws -> URLRequest {
        var comps = URLComponents()
        comps.scheme = "https"
        comps.host = "api.github.com"
        comps.path = "/repos/\(owner)/\(repo)/contents/\(path)"
        comps.queryItems = [URLQueryItem(name: "ref", value: branch)]
        guard let url = comps.url else { throw GitHubError.badURL }
        var req = URLRequest(url: url)
        req.setValue(raw ? "application/vnd.github.raw+json" : "application/vnd.github+json",
                     forHTTPHeaderField: "Accept")
        if !token.isEmpty {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return req
    }

    private func fetch(_ path: String, raw: Bool) async throws -> Data {
        let (data, resp) = try await URLSession.shared.data(for: try request(path, raw: raw))
        guard let http = resp as? HTTPURLResponse else { throw GitHubError.badURL }
        guard (200..<300).contains(http.statusCode) else { throw GitHubError.http(http.statusCode) }
        return data
    }

    /// ファイルの中身を取得してデコード
    func file<T: Decodable>(_ path: String, as type: T.Type) async throws -> T {
        var data = try await fetch(path, raw: true)
        // 防御: Python製JSONに稀に混入する NaN/Infinity は JSON 仕様違反で、
        // 標準デコーダが解釈できない。null に置換してから読む。
        if let s = String(data: data, encoding: .utf8), s.contains("NaN") || s.contains("Infinity") {
            let cleaned = s.replacingOccurrences(
                of: "(?<=[\\s:,\\[])-?(NaN|Infinity)(?=[\\s,\\]}])",
                with: "null", options: .regularExpression)
            data = cleaned.data(using: .utf8) ?? data
        }
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw GitHubError.decode("\(path): \(error.localizedDescription)")
        }
    }

    /// ディレクトリのファイル一覧を取得
    func list(_ dir: String) async throws -> [RepoFile] {
        let data = try await fetch(dir, raw: false)
        do {
            return try JSONDecoder().decode([RepoFile].self, from: data)
        } catch {
            throw GitHubError.decode("\(dir): \(error.localizedDescription)")
        }
    }
}
