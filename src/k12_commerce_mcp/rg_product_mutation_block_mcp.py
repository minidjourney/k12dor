"""Local-only deny records for RG product create/modify shared seller URI."""

from typing import Literal

from .models.common import CanonicalModel


class RgProductMutationBlock(CanonicalModel):
    channel: Literal["coupang_rocket_growth"] = "coupang_rocket_growth"
    operation_id: Literal["rg_product_create", "rg_product_modify"]
    method: Literal["POST", "PUT"]
    status: Literal["blocked"] = "blocked"
    rg_proof: Literal[False] = False
    shared_uri_promoted: Literal[False] = False
    official_rg_uri: Literal[False] = False
    reasons: tuple[str, ...] = ("shared_uri_not_rg_proof", "change_not_a_read")
    items: tuple[()] = ()


def block_rg_product_mutation(
    operation_id: Literal["rg_product_create", "rg_product_modify"],
) -> RgProductMutationBlock:
    return RgProductMutationBlock(
        operation_id=operation_id, method="POST" if operation_id == "rg_product_create" else "PUT"
    )
