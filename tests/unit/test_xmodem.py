"""Tests for XMODEM protocol transfer using mock I/O."""
import io
import os

import pytest
from xmodem import XMODEM, XMODEM1k

from worker import _fd_write


def make_mock_receiver(handshake=b'C', block_replies=None, eot_reply=b'\x06'):
    """Create mock getc/putc callbacks for testing XMODEM senders.

    handshake: bytes or list of bytes returned by getc() during handshake.
    block_replies: list of bytes returned by getc() after each putc(SOH/STX).
        Exhaustion defaults to ACK (b'\\x06').
    eot_reply: byte returned by getc() after putc(EOT).
    """
    if isinstance(handshake, bytes) and len(handshake) == 1:
        handshake = [handshake]
    handshake = list(handshake)
    block_replies = list(block_replies) if block_replies else []
    reply_iter = iter(block_replies)

    putc_log = []
    pending_response = None
    handshake_idx = 0
    handshake_complete = False

    def getc(size, timeout=1):
        nonlocal pending_response, handshake_idx, handshake_complete
        if not handshake_complete:
            if handshake_idx < len(handshake):
                r = handshake[handshake_idx]
                handshake_idx += 1
                return r
            handshake_complete = True
        if pending_response is not None:
            r = pending_response
            pending_response = None
            return r
        return None

    def putc(data, timeout=1):
        nonlocal pending_response, handshake_complete
        putc_log.append(data)
        if not handshake_complete and data[:1] in (b'\x01', b'\x02', b'\x04'):
            handshake_complete = True
        if data == b'\x04':
            pending_response = eot_reply
        elif data[:1] in (b'\x01', b'\x02'):
            try:
                pending_response = next(reply_iter)
            except StopIteration:
                pending_response = b'\x06'
        return len(data)

    return getc, putc, putc_log


class TestXmodemSend:
    def test_crc_transfer(self):
        """CRC mode (C handshake): full transfer succeeds."""
        getc, putc, log = make_mock_receiver(handshake=b'C')
        modem = XMODEM(getc, putc)
        stream = io.BytesIO(b'A' * 300)

        assert modem.send(stream, retry=3, timeout=0.1) is True
        assert len(log) >= 4  # 3 blocks + EOT

    def test_checksum_transfer(self):
        """Checksum mode (NAK handshake): full transfer succeeds."""
        getc, putc, log = make_mock_receiver(handshake=b'\x15')
        modem = XMODEM(getc, putc)
        stream = io.BytesIO(b'B' * 200)

        assert modem.send(stream, retry=3, timeout=0.1) is True
        assert len(log) >= 3  # 2 blocks + EOT

    def test_nak_then_ack_retry(self):
        """Receiver NAKs first block transmission, ACKs the retry."""
        replies = [b'\x15', b'\x06']
        getc, putc, log = make_mock_receiver(
            handshake=b'C', block_replies=replies,
        )
        modem = XMODEM(getc, putc)
        stream = io.BytesIO(b'X' * 128)

        assert modem.send(stream, retry=3, timeout=0.1) is True
        assert len(log) >= 3  # 2 putc for block 1 + EOT

    def test_nak_exhausted(self):
        """Receiver NAKs every attempt; sender fails after retries."""
        replies = [b'\x15'] * 20
        getc, putc, log = make_mock_receiver(
            handshake=b'C', block_replies=replies,
        )
        modem = XMODEM(getc, putc)
        stream = io.BytesIO(b'Y' * 200)

        assert modem.send(stream, retry=3, timeout=0.1) is False

    def test_receiver_cancel_handshake(self):
        """Receiver sends CAN CAN during handshake; sender aborts."""
        getc, putc, log = make_mock_receiver(
            handshake=[b'\x18', b'\x18'],
        )
        modem = XMODEM(getc, putc)
        stream = io.BytesIO(b'Z' * 100)

        assert modem.send(stream, retry=3, timeout=0.1) is False

    def test_timeout_handshake(self):
        """Receiver never responds during handshake; sender times out."""
        getc, putc, log = make_mock_receiver(
            handshake=[],  # no handshake bytes
        )
        modem = XMODEM(getc, putc)
        stream = io.BytesIO(b'W' * 100)

        assert modem.send(stream, retry=3, timeout=0.1) is False

    def test_block_rollover(self):
        """Sequence number wraps correctly after 256 blocks."""
        replies = [b'\x06'] * 520  # enough ACKs for 257 blocks + EOT retries
        getc, putc, log = make_mock_receiver(
            handshake=b'C', block_replies=replies,
        )
        modem = XMODEM(getc, putc)
        stream = io.BytesIO(b'R' * (257 * 128))

        assert modem.send(stream, retry=16, timeout=0.1) is True

        soh_blocks = [d for d in log if d[:1] == b'\x01']
        assert len(soh_blocks) == 257

        # Verify first block is seq 1, 256th is seq 0, 257th is seq 1
        assert soh_blocks[0][1] == 1
        assert soh_blocks[255][1] == 0   # wraps at 256
        assert soh_blocks[256][1] == 1   # wraps back to 1

    def test_eot_no_ack(self):
        """Receiver doesn't ACK EOT; sender fails after retries."""
        getc, putc, log = make_mock_receiver(
            handshake=b'C', eot_reply=b'\x15',
        )
        modem = XMODEM(getc, putc)
        stream = io.BytesIO(b'Q' * 50)  # 1 block

        assert modem.send(stream, retry=3, timeout=0.1) is False
        eots = [d for d in log if d == b'\x04']
        assert len(eots) >= 4  # initial + 3 retries

    def test_callback(self):
        """Callback receives correct packet counts."""
        counts = []

        def cb(total, ok, err):
            counts.append((total, ok, err))

        getc, putc, log = make_mock_receiver(handshake=b'C')
        modem = XMODEM(getc, putc)
        stream = io.BytesIO(b'S' * 300)  # 3 blocks

        assert modem.send(stream, retry=3, timeout=0.1, callback=cb) is True
        assert len(counts) == 3
        assert counts[-1] == (3, 3, 0)

    def test_xmodem1k_transfer(self):
        """XMODEM-1K (1024-byte blocks, CRC-16) sends larger blocks."""
        getc, putc, log = make_mock_receiver(handshake=b'C')
        modem = XMODEM1k(getc, putc)
        stream = io.BytesIO(b'T' * 2000)  # 2 blocks

        assert modem.send(stream, retry=3, timeout=0.1) is True
        # STX (0x02) for 1K blocks
        stx_blocks = [d for d in log if d[:1] == b'\x02']
        assert len(stx_blocks) == 2
        assert len(stx_blocks[0]) == 1 + 2 + 1024 + 2  # STX + header + data + CRC16

    def test_cancelled_mid_transfer(self):
        """getc raises an exception mid-transfer; sender propagates it."""
        getc_call_count = [0]

        def getc(size, timeout=1):
            getc_call_count[0] += 1
            if getc_call_count[0] == 1:
                return b'C'
            if getc_call_count[0] >= 4:
                raise RuntimeError("cancelled")
            return b'\x06'

        def putc(data, timeout=1):
            return len(data)

        modem = XMODEM(getc, putc)
        stream = io.BytesIO(b'D' * 500)

        with pytest.raises(RuntimeError, match="cancelled"):
            modem.send(stream, retry=3, timeout=0.1)


class TestFdWrite:
    def test_full_write(self, monkeypatch):
        """_fd_write returns total bytes when os.write writes everything."""
        monkeypatch.setattr(os, 'write', lambda fd, data: len(data))
        assert _fd_write(0, b'\x01\x02\x03') == 3

    def test_partial_write(self, monkeypatch):
        """_fd_write loops until all bytes are written."""
        chunks = []

        def fake_write(fd, data):
            n = min(1, len(data))
            chunks.append(data[:n])
            return n

        monkeypatch.setattr(os, 'write', fake_write)
        assert _fd_write(0, b'\x01\x02\x03') == 3
        assert b''.join(chunks) == b'\x01\x02\x03'

    def test_write_zero_raises(self, monkeypatch):
        """_fd_write raises OSError if os.write returns 0."""
        call_count = [0]

        def fake_write(fd, data):
            call_count[0] += 1
            if call_count[0] == 1:
                return 2  # partial
            return 0  # error

        monkeypatch.setattr(os, 'write', fake_write)
        with pytest.raises(OSError, match="0 or negative"):
            _fd_write(0, b'\x01\x02\x03')

    def test_handles_empty_data(self):
        """Writing empty data is a no-op."""
        assert _fd_write(0, b'') == 0
