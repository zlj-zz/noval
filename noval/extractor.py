from typing import Iterator, List, Tuple, Union, Optional
import re
import unicodedata

from .utils import splicing_url, get_keyword_pattern
from .const import DATETIME_PATTERN, DETAIL_KEYWORD, HIGH_WEIGHT_KEYWORD

import numpy as np
from lxml.html import fromstring, HtmlElement


high_weight_keyword_pattern = get_keyword_pattern(HIGH_WEIGHT_KEYWORD)
detail_keyword_pattern = get_keyword_pattern(DETAIL_KEYWORD)


def html2element(html: str) -> HtmlElement:
    # 使用 NFKC 对网页源代码进行归一化，把特殊符号转换为普通符号
    html = unicodedata.normalize("NFKC", html)

    html = re.sub("</?br.*?>", "\n", html)
    # sourcery skip: inline-immediately-returned-variable
    element = fromstring(html)
    return element


def iter_node(element: HtmlElement) -> Iterator:
    yield element
    for sub_element in element:
        if isinstance(sub_element, HtmlElement):
            yield from iter_node(sub_element)


def count_text_tag(element: HtmlElement, tag: str) -> int:
    """当前标签下面的 text()和给定标签，都应该进行统计"""

    tag_num = len(element.xpath(f".//{tag}"))
    direct_text = len(element.xpath("text()"))
    return tag_num + direct_text


def get_all_text_of_element(element_list: Union[List, HtmlElement]) -> List[str]:
    if not isinstance(element_list, list):
        element_list = [element_list]

    text_list = []
    for element in element_list:
        element_flag = element.getroottree().getpath(element)

        element_text_list = []
        for text in element.xpath(".//text()"):
            text = text.strip()
            if not text:
                continue
            clear_text = re.sub(r"[^\S\n]+", " ", text, flags=re.S)
            element_text_list.append(clear_text)
        text_list.extend(element_text_list)
    return text_list


def need_skip_ltgi(ti: int, lti: int) -> bool:
    """
    在这种情况下，tgi = ltgi = 2，计算公式的分母为0. 为了把这种情况和列表页全是链接的
    情况区分出来，所以要做一下判断。检查节点下面所有 a 标签的超链接中的文本数量与本节点
    下面所有文本数量的比值。如果超链接的文本数量占比极少，那么此时，ltgi 应该忽略

    Args:
        ti: 节点 i 的字符串字数
        lti: 节点 i 的带链接的字符串字数
    """

    # if lti == 0:
    #     return False

    return ti // (lti + 1) > 10  # 正文的字符数量是链接字符数量的十倍以上


def increase_tag_weight(ti: int, element: HtmlElement) -> int:
    """如果标签为 `<content>` 这类更容易包含内容的标签，则增加该节点的权重."""

    tag = element.tag.lower()
    tag_class = element.get("class", "").lower()

    if high_weight_keyword_pattern.search(
        tag_class
    ) or high_weight_keyword_pattern.search(tag):
        return ti + ti // 2
    return ti


def calc_text_density(element: HtmlElement) -> float:
    """
    根据公式：

            Ti - LTi
    TDi = -----------
            TGi - LTGi


    Ti:节点 i 的字符串字数
    LTi：节点 i 的带链接的字符串字数
    TGi：节点 i 的标签数
    LTGi：节点 i 的带连接的标签数

    TDi: 是衡量一个网页的每个结点文本密度, 如果一个结点的纯文本字数比带链接的文本字
         数明显多很多的时候, 该结点的文本密度就会很大

    :return:
    """

    ti_text = "\n".join(get_all_text_of_element(element))
    # ti_text = re.sub(r"[ \n]+", "\n", ti_text)
    ti = len(ti_text)
    ti = increase_tag_weight(ti, element)

    a_tag_list = element.xpath(".//a")
    lti = len("".join(get_all_text_of_element(a_tag_list)))

    tgi = len(element.xpath(".//*"))
    ltgi = len(a_tag_list)
    if (tgi - ltgi) == 0:
        if need_skip_ltgi(ti, lti):
            ltgi = 0
        else:
            return {
                "density": 0,
                "ti_text": ti_text,
                "ti": ti,
                "lti": lti,
                "tgi": tgi,
                "ltgi": ltgi,
            }
    density = (ti - lti) / (tgi + 1 - ltgi)  # 防止 tgi == ltgi == 0
    return {
        "density": density,
        "ti_text": ti_text,
        "ti": ti,
        "lti": lti,
        "tgi": tgi,
        "ltgi": ltgi,
    }


def count_punctuation_num(text: str) -> int:
    """计算文字中符号的个数."""

    return sum(
        char in """！，。？、；：“”‘’《》「」【】%（）,.?:;'"!%()""" for char in text
    )


def calc_sbdi(text: str, ti: int, lti: int) -> float:
    """
             Ti - LTi
    SbDi = --------------
              Sbi + 1

    SbDi: 符号密度
    Sbi：符号数量

    :return:
    """

    sbi = count_punctuation_num(text)
    sbdi = (ti - lti) / (sbi + 1)
    return sbdi or 1  # sbdi 不能为0，否则会导致求对数时报错。


def calc_new_score(node_info_dict: dict) -> None:
    """
    score = 1 * ndi * log10(p_tag_count + 2) * log(sbdi)

    1：在论文里面，这里使用的是 log(std)，但是每一个密度都乘以相同的对数，他们的相对大小是不会改变的，所以我们没有必要计算
    ndi：节点 i 的文本密度
    p_tag_count: 正文所在标签数。例如正文在<p></p>标签里面，这里就是 p 标签数，如果正文在<div></div>标签，这里就是 div 标签数
    sbdi：节点 i 的符号密度
    """

    for node_hash, node_info in node_info_dict.items():
        score = (
            node_info["density"]
            * np.log10(node_info["p_tag_count"] + 2)
            * np.log(node_info["sbdi"])
        )
        node_info_dict[node_hash]["score"] = score


class Extractor:
    """
    Code reference: https://github.com/GeneralNewsExtractor/GeneralNewsExtractor
    Principle reference: https://kns.cnki.net/KCMS/detail/detail.aspx?dbname=CJFDLAST2019&filename=GWDZ201908029
    """

    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = base_url

    def set_base_url(self, url: str) -> "Extractor":
        self.base_url = url

        return self

    def _process_ndo(self, text_list: List, name: str):
        fiction = ""
        update_time = ""
        other = []

        for text in text_list:
            # name
            if name in text:
                fiction = text

            # update time.
            else:
                for dt in DATETIME_PATTERN:
                    if dt_obj := re.search(dt, text):
                        update_time = dt_obj[1]
                        break
                else:
                    other.append(text)

        return [fiction, update_time, ",".join(other)]

    def extract_search(
        self, html: str, name: str, cur_url: Optional[str] = None
    ) -> List[Tuple]:
        """提取小说搜索结果

        结果中应存在 `<a href='xxx.html'>name</a>`, 通过匹配所有 a 标签的内容是否包含给定的 name。
        匹配成功则认为该 a 标签为结果所需。

        使用 xpath 提取所有信息，目标结构认定为类似：

        <tr>
            <td><a href="target.html">name</a></td>
            <td>author</td>
            <td>update-time</td>
        </tr>
        """

        cur_url = cur_url or self.base_url or ""
        element = html2element(html)

        res = []

        for node in iter_node(element):
            if node.tag.lower() == "a":
                a_text = "".join(node.xpath(".//text()"))
                if name in a_text:
                    url = node.xpath(".//@href")
                    text_list = node.xpath("../..//text()")
                    clear_text_list = [
                        re.sub(r"\s+", " ", x) for x in text_list if x.strip()
                    ]
                    clear_text_list = self._process_ndo(clear_text_list, name)
                    text = "|".join(clear_text_list)
                    if url:
                        res.append((text, splicing_url(cur_url, url[0])))

        return res

    def extract_detail(self, html: str, cur_url: Optional[str] = None) -> str:
        """提取详情页"""

        cur_url = cur_url or self.base_url or ""
        element = html2element(html)

        for node in iter_node(element):
            if node.tag.lower() == "a":
                text = "".join(node.xpath(".//text()"))
                if detail_keyword_pattern.search(text):
                    return (
                        splicing_url(cur_url, url[0])
                        if (url := node.xpath(".//@href"))
                        else ""
                    )

    def _extract_chapters_with_tag(
        self, element: HtmlElement, tags: List[Tuple], min_valid_count: int = 20
    ):
        # out tag, inner tag, (invalid tag, invalid text)
        father, child, (sp, sp_text) = tags
        ul_list: List[HtmlElement] = element.xpath(f"//{father}")

        max_li_count: int = 0
        target_ul: Optional[HtmlElement] = None

        # 找到包含 `<li>` 标签最多的元素，默认该元素下包含了所有章节.
        for ul in ul_list:
            li_count = count_text_tag(ul, f"{child}")
            if li_count > max_li_count:
                max_li_count = li_count
                target_ul = ul

        if target_ul is None or max_li_count < min_valid_count * 2:
            return []

        # 删除无效章节
        if sp and sp_text:
            remove_flag = 0
            for i in target_ul:
                if i.tag == sp:
                    remove_flag = 1 if sp_text in (i.text or "") else 0

                if remove_flag == 1 and i.tag == child:
                    target_ul.remove(i)

        urls = target_ul.xpath(f".//{child}/a/@href")
        texts = target_ul.xpath(f".//{child}/a/text()")

        return zip(urls, texts)

    def extract_chapters(self, html: str, cur_url: Optional[str] = None) -> List[Tuple]:
        """提取小说章节列表

        这里认为小说章节放在列表标签中，例如：`ul>li`, 所以先提取出所有的 ul 标签，找到包含 li 最多的 ul 标签.
        如果最终的 ul 中包含的 li 个数小于设定的阈值，则认为没有章节列表.

        ul>li
        dl>dt,dd
        """

        cur_url = cur_url or self.base_url or ""
        element = html2element(html)

        res = []
        rules = [
            ("dl", "dd", ("dt", "最新章节")),
            ("ul", "li", ("", "")),
        ]

        for tags in rules:
            cs = self._extract_chapters_with_tag(element, tags, min_valid_count=20)
            if cs:
                break

        # print(list(cs.copy()))
        for url, text in cs:
            url = splicing_url(cur_url, url)
            res.append((text, url))

        return res

    def extract_content(self, html: str) -> str:
        """提取正文"""

        element = html2element(html)
        body: HtmlElement = element.xpath("//body")[0]

        node_info_list = {}

        for node in iter_node(body):
            node_hash = hash(node)
            density_info = calc_text_density(node)
            sbdi = calc_sbdi(
                density_info["ti_text"], density_info["ti"], density_info["lti"]
            )
            p_tag_count = count_text_tag(node, tag="p")

            node_info = {
                "ti": density_info["ti"],
                "lti": density_info["lti"],
                "tgi": density_info["tgi"],
                "ltgi": density_info["ltgi"],
                "density": density_info["density"],
                "text": density_info["ti_text"],
                "p_tag_count": p_tag_count,
                "sbdi": sbdi,
                "node": node,
            }
            node_info_list[node_hash] = node_info

        calc_new_score(node_info_list)

        result = sorted(
            node_info_list.items(), key=lambda x: x[1]["score"], reverse=True
        )

        # for i in range(5):
        #     print(result[i][1])

        return result[0][1]["text"]
