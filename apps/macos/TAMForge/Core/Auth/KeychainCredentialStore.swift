import Foundation
import Security

protocol RefreshCredentialStore: Sendable {
    func activeRefreshToken() throws -> String?
    func storeActiveRefreshToken(_ token: String) throws
    func removeActiveRefreshToken() throws
    func pendingRevocationToken() throws -> String?
    func storePendingRevocationToken(_ token: String) throws
    func removePendingRevocationToken() throws
}

enum KeychainCredentialError: Error, Equatable {
    case accessDenied
    case invalidCredential
    case operationFailed(OSStatus)
}

struct KeychainCredentialStore: RefreshCredentialStore {
    static let service = "com.tamforge.native-auth"
    static let activeAccount = "active-refresh-token"
    static let pendingAccount = "pending-revocation-token"

    func activeRefreshToken() throws -> String? {
        try read(account: Self.activeAccount)
    }

    func storeActiveRefreshToken(_ token: String) throws {
        try store(token, account: Self.activeAccount)
    }

    func removeActiveRefreshToken() throws {
        try remove(account: Self.activeAccount)
    }

    func pendingRevocationToken() throws -> String? {
        try read(account: Self.pendingAccount)
    }

    func storePendingRevocationToken(_ token: String) throws {
        try store(token, account: Self.pendingAccount)
    }

    func removePendingRevocationToken() throws {
        try remove(account: Self.pendingAccount)
    }

    static func baseQuery(account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecAttrSynchronizable as String: false,
        ]
    }

    static func dataProtectionQuery(account: String) -> [String: Any] {
        var query = baseQuery(account: account)
        query[kSecUseDataProtectionKeychain as String] = true
        return query
    }

    static func fallbackQuery(account: String, after status: OSStatus) -> [String: Any]? {
        status == errSecMissingEntitlement ? baseQuery(account: account) : nil
    }

    static func decodedRead(status: OSStatus, value: CFTypeRef?) throws -> String? {
        if status == errSecItemNotFound {
            return nil
        }
        if status == errSecInteractionNotAllowed || status == errSecAuthFailed {
            throw KeychainCredentialError.accessDenied
        }
        guard status == errSecSuccess else {
            throw KeychainCredentialError.operationFailed(status)
        }
        guard let data = value as? Data,
              let token = String(data: data, encoding: .utf8),
              isValidToken(token)
        else {
            throw KeychainCredentialError.invalidCredential
        }
        return token
    }

    static func itemToAdd(
        tokenData: Data,
        account: String,
        query: [String: Any]? = nil
    ) -> [String: Any] {
        var item = query ?? baseQuery(account: account)
        item[kSecValueData as String] = tokenData
        if item[kSecUseDataProtectionKeychain as String] as? Bool == true {
            item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        }
        return item
    }

    private func read(account: String) throws -> String? {
        let (status, item) = Self.withCompatibleQuery(account: account) { query in
            var query = query
            query[kSecReturnData as String] = true
            query[kSecMatchLimit as String] = kSecMatchLimitOne
            var item: CFTypeRef?
            let status = SecItemCopyMatching(query as CFDictionary, &item)
            return (status, item)
        }
        return try Self.decodedRead(status: status, value: item)
    }

    private func store(_ token: String, account: String) throws {
        guard Self.isValidToken(token), let data = token.data(using: .utf8) else {
            throw KeychainCredentialError.invalidCredential
        }
        let update: [String: Any] = [kSecValueData as String: data]
        let (status, _) = Self.withCompatibleQuery(account: account) { query in
            var status = SecItemUpdate(query as CFDictionary, update as CFDictionary)
            if status == errSecItemNotFound {
                let item = Self.itemToAdd(tokenData: data, account: account, query: query)
                status = SecItemAdd(item as CFDictionary, nil)
            }
            return (status, ())
        }
        try Self.requireSuccess(status)
    }

    private func remove(account: String) throws {
        let (status, _) = Self.withCompatibleQuery(account: account) { query in
            (SecItemDelete(query as CFDictionary), ())
        }
        if status != errSecItemNotFound {
            try Self.requireSuccess(status)
        }
    }

    private static func withCompatibleQuery<Value>(
        account: String,
        operation: ([String: Any]) -> (OSStatus, Value)
    ) -> (OSStatus, Value) {
        let result = operation(dataProtectionQuery(account: account))
        if let fallback = fallbackQuery(account: account, after: result.0) {
            return operation(fallback)
        }
        return result
    }

    private static func requireSuccess(_ status: OSStatus) throws {
        if status == errSecInteractionNotAllowed || status == errSecAuthFailed {
            throw KeychainCredentialError.accessDenied
        }
        guard status == errSecSuccess else {
            throw KeychainCredentialError.operationFailed(status)
        }
    }

    private static func isValidToken(_ token: String) -> Bool {
        isNativeOpaqueToken(token)
    }
}
