#pragma once

#include "storage.hpp"

#include <cstdint>
#include <filesystem>
#include <vector>

namespace bams {

enum class OperationType : std::uint8_t {
    WriteRecord = 1,
};

struct WalOperation {
    OperationType type{OperationType::WriteRecord};
    std::uint64_t student_id{};
    std::vector<std::uint8_t> payload;
};

class WAL {
public:
    // Opens or creates the append-only log associated with the storage file.
    WAL(const std::filesystem::path& log_path, StorageEngine& storage);
    ~WAL();

    WAL(const WAL&) = delete;
    WAL& operator=(const WAL&) = delete;

    // Appends an operation, writes its checksum, and fsyncs before commit proceeds.
    std::uint64_t log_write(const WalOperation& operation);

    // Replays valid operations after the last checkpoint into the main storage file.
    std::size_t replay_log_on_startup();

    // Marks the durable log position represented by flushed storage pages.
    void checkpoint();

private:
    std::filesystem::path log_path_;
    StorageEngine& storage_;
    std::uint64_t checkpoint_lsn_{};
};

}  // namespace bams
