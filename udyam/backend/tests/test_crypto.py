import pytest
from cryptography.fernet import Fernet

from app import crypto

GOOD = Fernet.generate_key().decode()


@pytest.mark.parametrize("pasted", [GOOD, f" {GOOD}\n", f'"{GOOD}"', f"'{GOOD}'", f"KYC_ENC_KEY={GOOD}", f'KYC_ENC_KEY="{GOOD}" '])
def test_common_paste_mistakes_still_give_the_same_key(pasted):
    assert crypto.clean_key(pasted) == GOOD


def test_hints_describe_the_problem_without_leaking_the_key():
    short = GOOD[:30]
    hints = " ".join(crypto.key_hints(short))
    assert "length is 30" in hints and "'='" in hints and short not in hints
    assert crypto.key_hints(GOOD) == []
    assert "empty" in " ".join(crypto.key_hints('""'))
