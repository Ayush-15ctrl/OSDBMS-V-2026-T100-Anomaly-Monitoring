#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <vector>

namespace bams {

// Fixed-width data keeps the on-disk record layout deterministic and page-addressable.
inline constexpr std::size_t kPageSize = 4096;
inline constexpr std::size_t kEventTypeBytes = 32;

struct EventRecord {
    std::uint64_t student_id{};
    std::array<char, kEventTypeBytes> event_type{};
    std::uint64_t timestamp{};
    double value{};
};

struct PageHeader {
    std::uint64_t page_id{};
    std::uint32_t record_count{};
    std::uint32_t checksum{};
};

inline constexpr std::size_t kRecordsPerPage =
    (kPageSize - sizeof(PageHeader)) / sizeof(EventRecord);

struct Page {
    PageHeader header{};
    std::array<EventRecord, kRecordsPerPage> records{};
    std::array<std::byte,
               kPageSize - sizeof(PageHeader) -
                   (kRecordsPerPage * sizeof(EventRecord))> reserved{};
};

static_assert(sizeof(Page) == kPageSize,
              "Page layout must remain exactly one fixed-size disk page");

class StorageEngine {
public:
    // Opens or creates the raw page file used by the storage engine.
    explicit StorageEngine(const std::filesystem::path& file_path,
                           std::size_t page_size = kPageSize);
    ~StorageEngine();

    StorageEngine(const StorageEngine&) = delete;
    StorageEngine& operator=(const StorageEngine&) = delete;

    // Appends a fixed-size event record and returns its logical record location.
    std::uint64_t write_record(std::uint64_t student_id,
                               const EventRecord& event);

    // Reads matching records from the student index/order starting at offset.
    std::vector<EventRecord> read_records(std::uint64_t student_id,
                                           std::size_t offset,
                                           std::size_t count) const;

    // Writes dirty pages and performs the durability barrier for crash safety.
    void flush_to_disk();

    // Loads one page for the buffer pool and storage recovery paths.
    Page read_page(std::uint64_t page_id) const;

    // Writes one complete page using the fixed page format.
    void write_page(const Page& page);

    // Returns the configured page size for buffer-pool sizing and validation.
    std::size_t page_size() const noexcept;

private:
    std::filesystem::path file_path_;
    std::size_t page_size_;
};

}  // namespace bams
