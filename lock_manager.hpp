#pragma once

#include <cstdint>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <unordered_map>

namespace bams {

class LockManager {
public:
    LockManager() = default;
    ~LockManager();

    LockManager(const LockManager&) = delete;
    LockManager& operator=(const LockManager&) = delete;

    // Shared ownership permits concurrent readers of one student's event stream.
    void acquire_read_lock(std::uint64_t student_id);
    void release_read_lock(std::uint64_t student_id);

    // Exclusive ownership serializes writers for one student only.
    void acquire_write_lock(std::uint64_t student_id);
    void release_write_lock(std::uint64_t student_id);

private:
    struct StudentLock;

    // This mutex protects only lock-object creation and lookup, never the student critical section.
    mutable std::mutex map_mutex_;
    std::unordered_map<std::uint64_t, std::shared_ptr<StudentLock>> locks_;
};

}  // namespace bams
